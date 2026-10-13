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

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user, require_permission
from db import get_db
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from models.user import User
from schemas.skills import (
    AdminUserSkillsOut,
    SkillMatrixOut,
    SkillMatrixUser,
    UserSkillsOut,
)
from utils.csv_safe import csv_safe
from utils.skills import (
    WINDOWS,
    cached_skill_matrix,
    cached_user_skill_detail,
    cached_user_skills,
)

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


def _sorted_users(matrix: dict, sort: str, direction: str) -> list[dict]:
    """Order the cached user list per request. ``total`` (the default) ranks by
    total weighted points; a skill key ranks by that column's weighted value.
    Sorting the whole list before pagination is what makes sort truthful across
    pages — and it's cheap, the compute/cache did the heavy lifting."""
    if sort == "total":
        key = lambda u: u["total_weighted"]  # noqa: E731
    elif sort in matrix["skills"]:
        key = lambda u: u["scores"].get(sort, {}).get("weighted", 0)  # noqa: E731
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unknown sort column",
        )
    # Two-pass stable sort: name first, then the requested key — so ties keep a
    # deterministic order and pages never shuffle between requests.
    by_name = sorted(matrix["users"], key=lambda u: (u["display_name"] or "").lower())
    return sorted(by_name, key=key, reverse=direction == "desc")


def _require_window(window: str) -> str:
    """422 on anything outside the allowlist — windows key the cache, so an
    open-ended value would grow the keyspace per request (#440)."""
    if window not in WINDOWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unknown window",
        )
    return window


@admin_router.get("", response_model=SkillMatrixOut)
async def skill_matrix(
    _user: User = Depends(require_permission("view_global_analytics")),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=_DEFAULT_PAGE, ge=1, le=_MAX_PAGE),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="total", max_length=100),
    direction: str = Query(default="desc", pattern="^(asc|desc)$"),
    window: str = Query(default="all", max_length=10),
) -> SkillMatrixOut:
    """Every user × skill, cross-competition (Administrator only). The shared
    ``skills`` axis and the per-column ``population`` footer are returned whole;
    ``users`` is the requested page of the requested ordering."""
    await _require_skills_enabled(db)
    matrix = await cached_skill_matrix(db, _require_window(window))
    users = _sorted_users(matrix, sort, direction)
    page = users[offset : offset + limit]
    return SkillMatrixOut(
        skills=matrix["skills"],
        users=[SkillMatrixUser(**u) for u in page],
        population=matrix["population"],
        total_users=len(users),
        limit=limit,
        offset=offset,
    )


@admin_router.get("/export")
async def skill_matrix_export(
    _user: User = Depends(require_permission("view_global_analytics")),
    db: AsyncSession = Depends(get_db),
    window: str = Query(default="all", max_length=10),
) -> Response:
    """The whole matrix as CSV (no pagination) for off-platform selection work.
    Every cell goes through ``csv_safe`` (GHSA-352q): display names are
    competitor-controlled and this file is opened in a spreadsheet."""
    await _require_skills_enabled(db)
    matrix = await cached_skill_matrix(db, _require_window(window))
    skills = matrix["skills"]

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    header = ["User", "Total points", "Total solves"]
    for skill in skills:
        header += [
            f"{skill} (points)", f"{skill} (solved)", f"{skill} (available)",
            f"{skill} (attempts)", f"{skill} (hints)", f"{skill} (first bloods)",
        ]
    writer.writerow([csv_safe(h) for h in header])
    for u in matrix["users"]:
        row = [u["display_name"], u["total_weighted"], u["total"]]
        for skill in skills:
            cell = u["scores"].get(skill)
            row += (
                [
                    cell["weighted"], cell["solved"], cell["available"],
                    cell["attempts"], cell["hints"], cell["first_bloods"],
                ]
                if cell
                else [0, 0, "", 0, 0, 0]
            )
        writer.writerow([csv_safe(v) for v in row])

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="skills-matrix.csv"'},
    )


@admin_router.get("/users/{user_id}", response_model=AdminUserSkillsOut)
async def user_skill_detail(
    user_id: str,
    _user: User = Depends(require_permission("view_global_analytics")),
    db: AsyncSession = Depends(get_db),
    window: str = Query(default="all", max_length=10),
) -> AdminUserSkillsOut:
    """One user's drill-down (#440): per-skill stats plus their recent solve
    rows with attempts/hints/first-blood context. Same gates as the matrix; an
    unknown user is an undisclosing 404."""
    await _require_skills_enabled(db)
    detail = await cached_user_skill_detail(db, user_id, _require_window(window))
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return AdminUserSkillsOut(**detail)
