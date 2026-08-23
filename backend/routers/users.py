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

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from auth.identity import display_name_taken, email_taken
from auth.security import ahash_many, hash_password
from db import get_db, utcnow
from models.competition import Competition
from models.role import Role, RoleAssignment
from models.user import RefreshSession, User
from schemas.user import (
    UserAccountOut,
    UserCreate,
    UserImportReport,
    UserImportRowOut,
    UserUpdate,
)
from utils.api_tokens import emit_revoked, revoke_user_api_tokens
from utils.event_bus import event_bus
from utils.uploads import read_upload_capped
from utils.user_import import (
    RowPlan,
    UserImportError,
    UserImportTooLarge,
    parse_users_csv,
    plan_user_import,
)

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
        avatar_updated_at=user.avatar_updated_at,
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
        # Admin-created accounts are exempt from email verification (#74) — an
        # administrator minting the account is itself the vouching step.
        email_verified_at=utcnow(),
    )
    db.add(user)
    await db.commit()
    await event_bus.emit(
        "user.created",
        {"user_id": user.id, "email": user.email, "actor_user_id": current_user.id},
    )
    return await _out(db, user)


# A roster CSV is tiny — a few MB covers the row cap many times over; the cap
# exists so the parse loop's peak allocation stays bounded (utils/uploads.py).
_IMPORT_MAX_BYTES = 5 * 1024 * 1024


@router.post("/import", response_model=UserImportReport)
async def import_users(
    file: UploadFile = File(...),
    dry_run: bool = False,
    default_competition_id: str | None = Form(default=None),
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> UserImportReport:
    """Mass user import from CSV (#171) — the bulk counterpart to ``POST /``.

    Two-phase: ``?dry_run=true`` validates and returns the per-row report with
    **no writes**; the plain call re-runs the identical plan and commits the
    valid rows in **one transaction** (so a preview→confirm race just turns a
    row into a skip, and a mid-batch failure leaves nothing behind). Accounts
    follow single-create semantics exactly (argon2 hash, email pre-verified,
    no domain allowlist); role rows follow ``roles.assign_role`` semantics with
    the same escalation containment, downgraded from a 403 to a per-row warning.

    Event shape is the bulk-op convention: **no** per-row ``user.created``
    flood, one ``users.imported`` summary — but every role grant still emits
    its own ``role.assigned``, because privilege changes must stay individually
    attributable in the audit log.
    """
    if default_competition_id is not None:
        if await db.get(Competition, default_competition_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
            )

    blob = await read_upload_capped(file, _IMPORT_MAX_BYTES)
    try:
        rows, ignored_columns = parse_users_csv(blob)
    except UserImportTooLarge as exc:
        # Literal 413 (not status.HTTP_413_*) — the constant name churned across
        # Starlette versions (same precedent as roles.py's literal 422).
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except UserImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    plans = await plan_user_import(db, current_user, rows, default_competition_id)
    to_create = [p for p in plans if p.status == "create"]
    to_assign = [p for p in plans if p.role_action == "assign"]

    granted: list[tuple[str, RowPlan]] = []  # (subject_user_id, plan)
    if not dry_run:
        if to_create or to_assign:
            # argon2 is deliberately CPU-slow; hash the batch concurrently on
            # the cores-sized bulk pool (#207) so a large import finishes under
            # a timeout without oversubscribing the login pool. Order preserved.
            hashes = await ahash_many([p.password for p in to_create])
            new_users: dict[int, User] = {}
            for plan, pw_hash in zip(to_create, hashes):
                account = User(
                    email=plan.email,
                    display_name=plan.display_name,
                    password_hash=pw_hash,
                    # Same vouching rule as single create (#74): the admin
                    # minting the account is the verification step.
                    email_verified_at=utcnow(),
                )
                db.add(account)
                new_users[plan.line] = account
            await db.flush()
            for plan in to_assign:
                subject_id = plan.existing_user_id or new_users[plan.line].id
                db.add(
                    RoleAssignment(
                        user_id=subject_id,
                        competition_id=plan.target_competition_id,
                        role_id=plan.role_id,
                    )
                )
                granted.append((subject_id, plan))
            try:
                await db.commit()
            except IntegrityError as exc:
                # The plan is checked against a snapshot; a concurrent write
                # between plan and commit can still trip a unique constraint.
                # Atomic by design: nothing landed, and a re-run turns the
                # conflicting rows into skips.
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "A conflicting account appeared while importing — "
                        "nothing was created. Re-run the import; existing "
                        "rows will be skipped."
                    ),
                ) from exc

        # Commit before emitting (the audit consumer opens its own session).
        # Role grants are audited individually — who got what, granted by whom.
        for subject_id, plan in granted:
            await event_bus.emit(
                "role.assigned",
                {
                    "user_id": current_user.id,
                    "subject_user_id": subject_id,
                    "role_id": plan.role_id,
                    "role_name": plan.role_name,
                    "competition_id": plan.target_competition_id,
                },
            )
        await event_bus.emit(
            "users.imported",
            {
                "user_id": current_user.id,
                "created": len(to_create),
                "skipped": sum(p.status == "skip" for p in plans),
                "roles_assigned": len(granted),
            },
        )

    return UserImportReport(
        dry_run=dry_run,
        total=len(plans),
        created=len(to_create),
        skipped=sum(p.status == "skip" for p in plans),
        errors=sum(p.status == "error" for p in plans),
        roles_assigned=len(to_assign),
        roles_skipped=sum(p.role_action == "skip" for p in plans),
        ignored_columns=ignored_columns,
        rows=[
            UserImportRowOut(
                row=p.line,
                display_name=p.display_name,
                email=p.email,
                role=p.role_name,
                competition=p.competition_name,
                status=p.status,
                reason=p.reason,
                role_action=p.role_action,
                role_reason=p.role_reason,
            )
            for p in plans
        ],
    )


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
    renamed_from: str | None = None
    if body.display_name is not None and body.display_name != user.display_name:
        if await display_name_taken(db, body.display_name, exclude_id=user.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That display name is already taken",
            )
        renamed_from = user.display_name
        user.display_name = body.display_name
        # Stamp the cooldown even on an admin rename: fixing an offensive name
        # must stop the user renaming straight back (the admin bypasses the
        # *check*, not the clock — models.user.username_change_allowed_at).
        user.username_changed_at = utcnow()
    revoked_tokens: list[str] = []
    if body.password is not None:
        user.password_hash = hash_password(body.password)
        # A reset forces re-login everywhere. An administrator setting someone
        # else's password means lockout or compromise, not routine rotation, so
        # their API tokens die with their sessions (#75) — otherwise a leaked
        # token would outlive the very intervention meant to contain it.
        await _revoke_sessions(db, user.id)
        revoked_tokens = await revoke_user_api_tokens(db, user.id)
    await db.commit()
    await event_bus.emit(
        "user.updated", {"user_id": user.id, "actor_user_id": current_user.id}
    )
    if renamed_from is not None:
        # A rename is its own audited fact (who was previously what) on top of
        # the generic user.updated — same event the self-service path emits.
        await event_bus.emit(
            "user.renamed",
            {
                "user_id": user.id,
                "old_name": renamed_from,
                "new_name": user.display_name,
                "actor_user_id": current_user.id,
            },
        )
    await emit_revoked(revoked_tokens, user_id=user.id, actor_id=current_user.id)
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
    # Revoke rather than merely suspend: the is_active check alone would let
    # every previously-issued token spring back to life on unban (#75), so an
    # admin who banned a compromised account and later restored it would
    # silently re-arm the attacker's credential.
    revoked_tokens = await revoke_user_api_tokens(db, user.id)
    await db.commit()
    await event_bus.emit(
        "user.banned", {"user_id": user.id, "actor_user_id": current_user.id}
    )
    await emit_revoked(revoked_tokens, user_id=user.id, actor_id=current_user.id)
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
