"""Admin user management (§7 — Users & Roles).

The account directory + lifecycle an Administrator drives: list/search accounts,
create one, edit it (including a password reset), soft-ban/unban, and hard-delete.
Global-scoped and Administrator-only among the built-ins — reads gate on
``view_all_users``, writes on ``manage_users``.

Per-competition role *assignment* stays on Admin → Roles (§7.4); this page shows
only the platform-wide distinction (holds the global Administrator role or not).

Two lockout guards, mirroring the roles router: you can't ban/delete **yourself**,
and you can't ban/delete the **last active Administrator** (an install must keep
one account that can manage it). A ban and a password reset both revoke the
user's refresh sessions so the change takes effect immediately (the access-token
side is enforced in ``auth/deps.get_current_user``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from auth.identity import display_name_taken, email_taken
from auth.security import hash_password
from db import get_db, utcnow
from models.role import Role, RoleAssignment
from models.user import RefreshSession, User
from schemas.user import UserAccountOut, UserCreate, UserUpdate
from utils.event_bus import event_bus

router = APIRouter(prefix="/api/users", tags=["users"])

ADMINISTRATOR_ROLE_NAME = "Administrator"


async def _admin_user_ids(db: AsyncSession) -> set[str]:
    """User ids holding the global Administrator role."""
    rows = (
        await db.execute(
            select(RoleAssignment.user_id)
            .join(Role, Role.id == RoleAssignment.role_id)
            .where(Role.name == ADMINISTRATOR_ROLE_NAME)
        )
    ).all()
    return {user_id for (user_id,) in rows}


async def _out(db: AsyncSession, user: User, admin_ids: set[str] | None = None) -> UserAccountOut:
    if admin_ids is None:
        admin_ids = await _admin_user_ids(db)
    return UserAccountOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        is_administrator=user.id in admin_ids,
        created_at=user.created_at,
    )


async def _get_user_or_404(db: AsyncSession, user_id: str) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return user


async def _revoke_sessions(db: AsyncSession, user_id: str) -> None:
    for session in (
        await db.scalars(
            select(RefreshSession).where(
                RefreshSession.user_id == user_id,
                RefreshSession.revoked_at.is_(None),
            )
        )
    ).all():
        session.revoked_at = utcnow()


async def _guard_not_last_admin(db: AsyncSession, target: User, action: str) -> None:
    """Block an action that would leave no active Administrator."""
    admin_ids = await _admin_user_ids(db)
    if target.id not in admin_ids:
        return
    other_active_admins = await db.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.id.in_(admin_ids),
            User.id != target.id,
            User.is_active.is_(True),
        )
    )
    if not other_active_admins:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Can't {action} the last administrator",
        )


@router.get("", response_model=list[UserAccountOut])
async def list_users(
    q: str | None = None,
    _user: User = Depends(require_permission("view_all_users")),
    db: AsyncSession = Depends(get_db),
) -> list[UserAccountOut]:
    stmt = select(User).order_by(User.created_at)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.email).like(like),
                func.lower(User.display_name).like(like),
            )
        )
    users = (await db.scalars(stmt)).all()
    admin_ids = await _admin_user_ids(db)
    return [await _out(db, u, admin_ids) for u in users]


@router.post("", response_model=UserAccountOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> UserAccountOut:
    if await display_name_taken(db, body.display_name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That display name is already taken"
        )
    if body.email is not None and await email_taken(db, body.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )
    user = User(
        email=body.email,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.commit()
    await event_bus.emit(
        "user.created",
        {"user_id": user.id, "email": user.email, "actor_user_id": current_user.id},
    )
    return await _out(db, user)


@router.patch("/{user_id}", response_model=UserAccountOut)
async def update_user(
    user_id: str,
    body: UserUpdate,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> UserAccountOut:
    user = await _get_user_or_404(db, user_id)
    if body.email is not None and body.email != user.email:
        if await email_taken(db, body.email, exclude_id=user.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
            )
        user.email = body.email
    if body.display_name is not None and body.display_name != user.display_name:
        if await display_name_taken(db, body.display_name, exclude_id=user.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That display name is already taken",
            )
        user.display_name = body.display_name
    if body.password is not None:
        user.password_hash = hash_password(body.password)
        # A reset forces re-login everywhere.
        await _revoke_sessions(db, user.id)
    await db.commit()
    await event_bus.emit(
        "user.updated", {"user_id": user.id, "actor_user_id": current_user.id}
    )
    return await _out(db, user)


@router.post("/{user_id}/ban", response_model=UserAccountOut)
async def ban_user(
    user_id: str,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> UserAccountOut:
    user = await _get_user_or_404(db, user_id)
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="You can't ban yourself"
        )
    await _guard_not_last_admin(db, user, "ban")
    user.is_active = False
    await _revoke_sessions(db, user.id)
    await db.commit()
    await event_bus.emit(
        "user.banned", {"user_id": user.id, "actor_user_id": current_user.id}
    )
    return await _out(db, user)


@router.post("/{user_id}/unban", response_model=UserAccountOut)
async def unban_user(
    user_id: str,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> UserAccountOut:
    user = await _get_user_or_404(db, user_id)
    user.is_active = True
    await db.commit()
    await event_bus.emit(
        "user.unbanned", {"user_id": user.id, "actor_user_id": current_user.id}
    )
    return await _out(db, user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> None:
    user = await _get_user_or_404(db, user_id)
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="You can't delete yourself"
        )
    await _guard_not_last_admin(db, user, "delete")
    await db.delete(user)
    await db.commit()
    await event_bus.emit(
        "user.deleted", {"user_id": user_id, "actor_user_id": current_user.id}
    )
