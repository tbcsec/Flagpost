"""Auth/RBAC FastAPI dependencies (ARCHITECTURE.md §7.6).

``get_current_user`` resolves a trustworthy identity from the Bearer access
token; ``require_permission`` is the single shared enforcement point every
protected route goes through — never an inline role check (§1 principle 6,
ADR-0004). Adding a permission or changing what a role can do is a data
change, so route code never enumerates roles.
"""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.permissions import Scope, is_known, scope_of
from auth.security import decode_access_token
from db import get_db
from models.role import Role, RoleAssignment
from models.user import User

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await db.get(User, payload.get("sub"))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )
    # A banned account's still-valid access token is rejected immediately, not
    # just at next login (admin user management).
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account has been disabled",
        )
    return user


async def user_has_permission(
    db: AsyncSession,
    user_id: str,
    permission_key: str,
    competition_id: str | None,
) -> bool:
    """Resolve whether ``user_id`` holds ``permission_key`` in the given context.

    - A **global** role assignment (``competition_id IS NULL``) grants its
      permissions site-wide — this is how Administrator satisfies both global
      and competition-scoped checks for every competition (§7.3).
    - A **competition** role assignment grants its permissions only for that
      competition — this is how a Judge on competition A gets nothing on
      competition B (§7.5).
    """
    rows = (
        await db.execute(
            select(Role.permissions, RoleAssignment.competition_id)
            .join(RoleAssignment, RoleAssignment.role_id == Role.id)
            .where(RoleAssignment.user_id == user_id)
        )
    ).all()

    for permissions, assignment_competition_id in rows:
        if permission_key not in permissions:
            continue
        if assignment_competition_id is None:
            return True  # global assignment applies everywhere
        if (
            competition_id is not None
            and assignment_competition_id == competition_id
        ):
            return True
    return False


async def users_with_permission(
    db: AsyncSession,
    permission_key: str,
    competition_id: str | None,
) -> set[str]:
    """The set of user ids that hold ``permission_key`` in the given context.

    The inverse of :func:`user_has_permission` — "who can do X here" rather than
    "can this user do X". A **global** assignment (``competition_id IS NULL``)
    grants everywhere, so global Administrators are always included; a
    **competition** assignment grants only for its competition (§7.5). Used to
    resolve a notification/automation audience like "every staff member on this
    competition" (§4.4).
    """
    rows = (
        await db.execute(
            select(RoleAssignment.user_id, Role.permissions)
            .join(Role, Role.id == RoleAssignment.role_id)
            .where(
                (RoleAssignment.competition_id == competition_id)
                | (RoleAssignment.competition_id.is_(None))
            )
        )
    ).all()
    return {
        user_id
        for user_id, permissions in rows
        if permission_key in permissions
    }


def _competition_id_from_request(request: Request) -> str | None:
    """Best-effort extraction of the request's competition context.

    Competition-scoped routes carry ``competition_id`` as a path parameter
    (e.g. ``/api/competitions/{competition_id}``); fall back to a query param.
    Global-scoped permissions ignore this entirely.
    """
    return request.path_params.get("competition_id") or request.query_params.get(
        "competition_id"
    )


def require_permission(permission_key: str):
    """Return a dependency that 403s unless the current user holds the permission.

    Resolves the user's role for the request's competition context (or the
    global role, for global-scoped permissions) and checks the permission is
    in that role's set — otherwise 403 (§7.6).
    """
    if not is_known(permission_key):
        # Fail loudly at import/startup, not silently at request time — the
        # guard ADR-0004 asks for against typo'd permission strings.
        raise ValueError(f"Unknown permission key: {permission_key!r}")

    async def dependency(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        competition_id = (
            None
            if scope_of(permission_key) is Scope.GLOBAL
            else _competition_id_from_request(request)
        )
        if not await user_has_permission(
            db, current_user.id, permission_key, competition_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission_key}",
            )
        return current_user

    return dependency
