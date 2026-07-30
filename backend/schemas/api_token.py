"""Personal API token schemas (issue #75).

``ApiTokenOut`` never carries the raw token or its hash — only
``ApiTokenCreated`` (the mint response) does, and only once.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiTokenCreate(BaseModel):
    user_id: str
    description: str = Field(min_length=1, max_length=200)
    # No upper bound (owner call, issue #75) — any admin-chosen duration is
    # acceptable. The router guards the datetime arithmetic against overflow.
    expires_in_days: int = Field(gt=0)


class ApiTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    user_display_name: str
    description: str
    created_by_user_id: str | None
    created_by_display_name: str | None
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiTokenCreated(ApiTokenOut):
    # Shown once, at mint time — never persisted or returned again.
    token: str
