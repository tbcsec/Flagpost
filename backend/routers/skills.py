"""Skills web route (#364, ADR-0039) — the ``skills`` module.

One cross-competition read, a sanctioned §6.3 exception to competition scoping:
``GET /api/me/skills`` returns the caller's own skill web, **auth-only** — the
route shape is the authorization, like ``/api/me/certificates``. It 404s when the
site-wide switch (``site_settings.skills_enabled``) is off (the certificates
``_guard`` pattern, adapted to a site flag).

(The admin users×skills matrix from #364 was dropped for now — owner decision;
see the ADR-0039 amendment. The read model still exposes only the self view.)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user
from db import get_db
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from models.user import User
from schemas.skills import UserSkillsOut
from utils.skills import cached_user_skills

me_router = APIRouter(prefix="/api/me/skills", tags=["skills"])


async def _require_skills_enabled(db: AsyncSession) -> None:
    """404 when the skills web is disabled site-wide. Reads the settings row
    directly (an unconfigured instance defaults to on, matching the column
    default) with no ``get_or_create`` side effect on a read path."""
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
