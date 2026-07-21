"""Pydantic schemas for the audit-log query surface (§3.3)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_name: str
    payload: dict[str, Any]
    competition_id: str | None
    user_id: str | None
    created_at: datetime


class AuditLogPage(BaseModel):
    """One page of results plus the total match count for pagination."""

    items: list[AuditLogEntryOut]
    total: int
    limit: int
    offset: int
