"""Personal API token schemas (issue #75).

``ApiTokenOut`` never carries the raw token or its hash — only
``ApiTokenCreated`` (the mint response) does, and only once.

Note the deliberate absence of a ``user_id`` on ``ApiTokenCreate``: the holder
is always the authenticated caller, so there is no field through which anyone
could mint a token belonging to another account.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiTokenCreate(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    # No upper bound (owner call, issue #75) — any self-chosen duration is
    # acceptable. The router guards the datetime arithmetic against overflow.
    expires_in_days: int = Field(gt=0)


class ApiTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    # Resolved for the admin oversight list, where tokens from every account are
    # shown together; on the holder's own list it is always their own name.
    user_display_name: str
    description: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiTokenCreated(ApiTokenOut):
    # Shown once, at mint time — never persisted or returned again.
    token: str
