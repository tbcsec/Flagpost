"""Admin audit-log query surface (§3.3).

Every event the bus emits is persisted to ``audit_log`` (utils/audit_log.py);
this read-only endpoint lets a site administrator inspect that stream with
GitLab-issue-style filtering — by event type (exact or ``challenge.*`` prefix),
competition, actor, team (matched inside the event payload), a time window, and
a free-text search across the event name and payload.

Global admin surface: gated on ``view_audit_log`` (§7.1), which only the
Administrator role holds. Mounted through the ``audit_log`` module (§11.1,
required-core); the audit log is a cross-competition table, so the routes are
not competition-scoped even though they register through the loader like every
other feature.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.audit_log import AuditLogEntry
from models.user import User
from schemas.audit_log import AuditLogPage

router = APIRouter(prefix="/api/admin/audit-log", tags=["audit-log"])


def _apply_filters(
    stmt,
    *,
    event: str | None,
    competition_id: str | None,
    user_id: str | None,
    team_id: str | None,
    q: str | None,
    since: datetime | None,
    until: datetime | None,
):
    if event:
        # `challenge.*` (or a trailing `*`) is a prefix match; otherwise exact.
        if event.endswith(".*") or event.endswith("*"):
            prefix = event[:-2] if event.endswith(".*") else event[:-1]
            stmt = stmt.where(AuditLogEntry.event_name.like(f"{prefix}.%"))
        else:
            stmt = stmt.where(AuditLogEntry.event_name == event)
    if competition_id:
        stmt = stmt.where(AuditLogEntry.competition_id == competition_id)
    if user_id:
        stmt = stmt.where(AuditLogEntry.user_id == user_id)
    if team_id:
        # team_id lives inside the JSON payload (it isn't lifted to a column).
        # Portable JSON access: index → text, cross-dialect (SQLite/Postgres).
        stmt = stmt.where(
            AuditLogEntry.payload["team_id"].as_string() == team_id
        )
    if q:
        needle = f"%{q}%"
        stmt = stmt.where(
            AuditLogEntry.event_name.ilike(needle)
            | cast(AuditLogEntry.payload, String).ilike(needle)
        )
    if since:
        stmt = stmt.where(AuditLogEntry.created_at >= since)
    if until:
        stmt = stmt.where(AuditLogEntry.created_at <= until)
    return stmt


@router.get("", response_model=AuditLogPage)
async def query_audit_log(
    event: str | None = Query(None, description="Exact event or `challenge.*` prefix"),
    competition_id: str | None = None,
    user_id: str | None = None,
    team_id: str | None = None,
    q: str | None = Query(None, description="Free-text search over name + payload"),
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _current_user: User = Depends(require_permission("view_audit_log")),
    db: AsyncSession = Depends(get_db),
) -> AuditLogPage:
    filters = dict(
        event=event,
        competition_id=competition_id,
        user_id=user_id,
        team_id=team_id,
        q=q,
        since=since,
        until=until,
    )
    total = await db.scalar(
        _apply_filters(select(func.count(AuditLogEntry.id)), **filters)
    )
    rows = (
        await db.execute(
            _apply_filters(select(AuditLogEntry), **filters)
            .order_by(AuditLogEntry.created_at.desc(), AuditLogEntry.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return AuditLogPage(items=list(rows), total=total or 0, limit=limit, offset=offset)


@router.get("/event-names", response_model=list[str])
async def audit_log_event_names(
    _current_user: User = Depends(require_permission("view_audit_log")),
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    """Distinct event names present in the log — populates the filter dropdown."""
    rows = (
        await db.execute(
            select(AuditLogEntry.event_name).distinct().order_by(AuditLogEntry.event_name)
        )
    ).scalars().all()
    return list(rows)
