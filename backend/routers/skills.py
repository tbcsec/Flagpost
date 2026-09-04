"""Skills web routes (#364, ADR-0039) — the ``skills`` module.

Two cross-competition reads, both sanctioned §6.3 exceptions to competition
scoping:

- **self** (``GET /api/me/skills``): the caller's own skill web, auth-only — the
  route shape is the authorization, like ``/api/me/certificates``.
- **admin** (``GET /api/admin/skills``): the users × skills matrix, gated on
  ``view_global_analytics`` (Administrator-only), paginated over users.

Both 404 when the site-wide switch (``site_settings.skills_enabled``) is off — the
certificates ``_guard`` pattern, adapted from a per-competition to a site flag.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user, require_permission
from db import get_db
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from models.user import User
from schemas.skills import SkillMatrixOut, SkillMatrixUser, UserSkillsOut
from utils.skills import cached_skill_matrix, cached_user_skills

me_router = APIRouter(prefix="/api/me/skills", tags=["skills"])
admin_router = APIRouter(prefix="/api/admin/skills", tags=["skills"])

# The admin matrix can list every user, so page it. A generous default; capped so
# one request can't return an unbounded grid.
_DEFAULT_PAGE = 50
_MAX_PAGE = 200


async def _require_skills_enabled(db: AsyncSession) -> None:
    """404 when the skills web is disabled site-wide. Reads the settings row
    directly — an unconfigured instance (no row yet) defaults to on, matching the
    column default — with no ``get_or_create`` side effect on a read path."""
    row = await db.get(SiteSettings, SITE_SETTINGS_ID)
    if row is not None and not row.skills_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The skills web is disabled"
        )


@me_router.get("", response_model=UserSkillsOut)
async def my_skills(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserSkillsOut:
    """The caller's own cross-competition skill web — every event they've played,
    accumulated by category (ADR-0039)."""
    await _require_skills_enabled(db)
    return UserSkillsOut(**await cached_user_skills(db, current_user.id))


@admin_router.get("", response_model=SkillMatrixOut)
async def skill_matrix(
    _user: User = Depends(require_permission("view_global_analytics")),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=_DEFAULT_PAGE, ge=1, le=_MAX_PAGE),
    offset: int = Query(default=0, ge=0),
) -> SkillMatrixOut:
    """Every user × skill, cross-competition (Administrator only). The shared
    ``skills`` axis is returned whole; ``users`` is the requested page."""
    await _require_skills_enabled(db)
    matrix = await cached_skill_matrix(db)
    users = matrix["users"]
    page = users[offset : offset + limit]
    return SkillMatrixOut(
        skills=matrix["skills"],
        users=[SkillMatrixUser(**u) for u in page],
        total_users=len(users),
        limit=limit,
        offset=offset,
    )
