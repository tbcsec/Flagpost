"""Roles admin API (ARCHITECTURE.md §7.4, ROADMAP #21).

Lets an Administrator hand out narrower access than the three built-ins: list
roles, read the permission catalog, create/clone/edit/delete **custom** roles,
and assign/unassign them to users per competition or globally. Everything is
gated on the global ``manage_roles`` permission (§7.3 — Administrator-only among
the built-ins).

Invariants held here:
- **System roles are read-only** (§7.3): they can't be edited or deleted; an
  admin clones one into a custom role to vary it.
- A custom role defaults to ``competition`` scope (§7.4); its permission keys
  are validated against the catalog (§7.1).
- **Assignment scope must match the role**: a global role is assigned site-wide
  (``competition_id = None``), a competition role to one competition.
- The **last Administrator can't be unassigned**, so an install can't lock
  itself out of role management.

Every mutation emits its §3.2 event (``role.created`` / ``role.updated`` /
``role.deleted`` / ``role.assigned`` / ``role.unassigned``). No migration — the
``roles`` / ``role_assignments`` tables are Tier-0.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from auth.identity import find_by_identifier
from auth.permissions import PERMISSIONS, is_known
from db import get_db
from models.competition import Competition
from models.role import Role, RoleAssignment
from models.user import User
from schemas.role import (
    AssignmentCreate,
    AssignmentOut,
    PermissionOut,
    RoleCreate,
    RoleOut,
    RoleUpdate,
)
from utils.event_bus import event_bus

router = APIRouter(prefix="/api/roles", tags=["roles"])

ADMINISTRATOR_ROLE_NAME = "Administrator"


def _validate_permission_keys(keys: list[str]) -> None:
    unknown = sorted(k for k in keys if not is_known(k))
    if unknown:
        # Literal 422 (not status.HTTP_422_*) — the constant name churned across
        # Starlette versions; the code is stable.
        raise HTTPException(
            status_code=422,
            detail=f"Unknown permission keys: {', '.join(unknown)}",
        )


async def _name_taken(db: AsyncSession, name: str, *, exclude_id: str | None = None) -> bool:
    stmt = select(Role.id).where(Role.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Role.id != exclude_id)
    return await db.scalar(stmt) is not None


@router.get("", response_model=list[RoleOut])
async def list_roles(
    _: User = Depends(require_permission("manage_roles")),
    db: AsyncSession = Depends(get_db),
) -> list[Role]:
    # System roles first, then custom, each alphabetical — a stable editor order.
    result = await db.execute(
        select(Role).order_by(Role.is_system.desc(), Role.name)
    )
    return list(result.scalars().all())


@router.get("/catalog", response_model=list[PermissionOut])
async def permission_catalog(
    _: User = Depends(require_permission("manage_roles")),
) -> list[PermissionOut]:
    """The categorized permission catalog (§7.1) the editor renders as a matrix."""
    return [
        PermissionOut(
            key=p.key, category=p.category, scope=p.scope.value, reserved=p.reserved
        )
        for p in PERMISSIONS
    ]


@router.post("", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleCreate,
    current_user: User = Depends(require_permission("manage_roles")),
    db: AsyncSession = Depends(get_db),
) -> Role:
    scope = body.scope
    permissions = list(body.permissions)

    # Clone: seed scope + permissions from the source (system or custom), which
    # the body can still override.
    if body.clone_from is not None:
        source = await db.get(Role, body.clone_from)
        if source is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Source role not found"
            )
        scope = source.scope
        permissions = list(source.permissions)
        if "permissions" in body.model_fields_set:
            permissions = list(body.permissions)
        if "scope" in body.model_fields_set:
            scope = body.scope

    if await _name_taken(db, body.name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A role with that name already exists",
        )
    _validate_permission_keys(permissions)

    role = Role(
        name=body.name,
        description=body.description,
        is_system=False,
        scope=scope,
        permissions=permissions,
    )
    db.add(role)
    await db.commit()
    await db.refresh(role)

    await event_bus.emit(
        "role.created",
        {
            "user_id": current_user.id,
            "role_id": role.id,
            "name": role.name,
            "scope": role.scope,
            "cloned_from": body.clone_from,
        },
    )
    return role


@router.patch("/{role_id}", response_model=RoleOut)
async def update_role(
    role_id: str,
    body: RoleUpdate,
    current_user: User = Depends(require_permission("manage_roles")),
    db: AsyncSession = Depends(get_db),
) -> Role:
    role = await db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="System roles are read-only — clone to customize (§7.3)",
        )

    if body.name is not None and body.name != role.name:
        if await _name_taken(db, body.name, exclude_id=role.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A role with that name already exists",
            )
        role.name = body.name
    if body.description is not None:
        role.description = body.description
    if body.permissions is not None:
        _validate_permission_keys(body.permissions)
        role.permissions = list(body.permissions)

    await db.commit()
    await db.refresh(role)

    await event_bus.emit(
        "role.updated",
        {"user_id": current_user.id, "role_id": role.id, "name": role.name},
    )
    return role


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: str,
    current_user: User = Depends(require_permission("manage_roles")),
    db: AsyncSession = Depends(get_db),
) -> None:
    role = await db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="System roles can't be deleted"
        )
    # Block delete while assigned — so deleting a role never silently revokes
    # access from users mid-competition; unassign first.
    assigned = await db.scalar(
        select(func.count())
        .select_from(RoleAssignment)
        .where(RoleAssignment.role_id == role.id)
    )
    if assigned:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Role is assigned to {assigned} user(s); unassign before deleting",
        )

    name = role.name
    await db.delete(role)
    await db.commit()
    await event_bus.emit(
        "role.deleted", {"user_id": current_user.id, "role_id": role_id, "name": name}
    )


# --- Assignments -----------------------------------------------------------


def _assignment_out(assignment: RoleAssignment, user: User, role: Role, competition: Competition | None) -> AssignmentOut:
    return AssignmentOut(
        id=assignment.id,
        user_id=user.id,
        user_email=user.email,
        user_display_name=user.display_name,
        role_id=role.id,
        role_name=role.name,
        role_scope=role.scope,
        competition_id=assignment.competition_id,
        competition_name=competition.name if competition is not None else None,
    )


@router.get("/assignments", response_model=list[AssignmentOut])
async def list_assignments(
    role_id: str | None = None,
    competition_id: str | None = None,
    _: User = Depends(require_permission("manage_roles")),
    db: AsyncSession = Depends(get_db),
) -> list[AssignmentOut]:
    stmt = (
        select(RoleAssignment, User, Role, Competition)
        .join(User, User.id == RoleAssignment.user_id)
        .join(Role, Role.id == RoleAssignment.role_id)
        .outerjoin(Competition, Competition.id == RoleAssignment.competition_id)
        .order_by(Role.name, User.email)
    )
    if role_id is not None:
        stmt = stmt.where(RoleAssignment.role_id == role_id)
    if competition_id is not None:
        stmt = stmt.where(RoleAssignment.competition_id == competition_id)
    rows = await db.execute(stmt)
    return [_assignment_out(a, u, r, c) for a, u, r, c in rows.all()]


@router.post("/assignments", response_model=AssignmentOut, status_code=status.HTTP_201_CREATED)
async def assign_role(
    body: AssignmentCreate,
    current_user: User = Depends(require_permission("manage_roles")),
    db: AsyncSession = Depends(get_db),
) -> AssignmentOut:
    # Resolve by email *or* display name (username) so email-less accounts stay
    # assignable now that email is optional.
    user = await find_by_identifier(db, body.email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No user with that email or username",
        )
    role = await db.get(Role, body.role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    # Assignment scope must match the role scope (§7.5).
    competition: Competition | None = None
    if role.scope == "global":
        if body.competition_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A global role is assigned site-wide, not to a competition",
            )
    else:
        if body.competition_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A competition-scoped role needs a competition",
            )
        competition = await db.get(Competition, body.competition_id)
        if competition is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
            )

    existing = await db.scalar(
        select(RoleAssignment).where(
            RoleAssignment.user_id == user.id,
            RoleAssignment.competition_id == body.competition_id,
            RoleAssignment.role_id == role.id,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That user already holds this role in this scope",
        )

    assignment = RoleAssignment(
        user_id=user.id, competition_id=body.competition_id, role_id=role.id
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)

    await event_bus.emit(
        "role.assigned",
        {
            "user_id": current_user.id,  # actor
            "subject_user_id": user.id,
            "role_id": role.id,
            "role_name": role.name,
            "competition_id": body.competition_id,
        },
    )
    return _assignment_out(assignment, user, role, competition)


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_role(
    assignment_id: str,
    current_user: User = Depends(require_permission("manage_roles")),
    db: AsyncSession = Depends(get_db),
) -> None:
    assignment = await db.get(RoleAssignment, assignment_id)
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found"
        )
    role = await db.get(Role, assignment.role_id)

    # Never remove the last Administrator — an install must keep at least one
    # account that can manage roles, or it locks itself out.
    if role is not None and role.name == ADMINISTRATOR_ROLE_NAME and role.is_system:
        admin_count = await db.scalar(
            select(func.count())
            .select_from(RoleAssignment)
            .where(RoleAssignment.role_id == role.id)
        )
        if admin_count is not None and admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Can't remove the last administrator",
            )

    subject_user_id = assignment.user_id
    competition_id = assignment.competition_id
    role_id = assignment.role_id
    await db.delete(assignment)
    await db.commit()

    await event_bus.emit(
        "role.unassigned",
        {
            "user_id": current_user.id,
            "subject_user_id": subject_user_id,
            "role_id": role_id,
            "competition_id": competition_id,
        },
    )
