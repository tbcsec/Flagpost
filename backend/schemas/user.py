"""Admin user-management schemas (§7 — Users & Roles).

The account directory + create/edit surface an Administrator uses (gated on
``view_all_users`` / ``manage_users``). Distinct from ``schemas.auth.UserOut``
(a user's view of themselves after login) — this carries admin-only fields
(active/banned, whether they hold a global Administrator role).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr | None
    display_name: str
    is_active: bool
    # Holds the global Administrator role — the meaningful platform-wide role
    # (per-competition Judge/Participant roles vary and live on Admin → Roles).
    is_administrator: bool
    created_at: datetime
    # Profile picture flag/cache-buster (see UserOut) — the directory needs it
    # for the admin "remove picture" moderation action.
    avatar_updated_at: datetime | None = None


class UserCreate(BaseModel):
    # Display name is the login identifier (username); email is optional.
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=256)
    email: EmailStr | None = None


class UserUpdate(BaseModel):
    """Partial edit — only the provided fields change. A new password re-hashes
    and revokes the user's sessions (they must sign in again)."""

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)


class UserImportRowOut(BaseModel):
    """One CSV row's outcome in the mass-import report (#171). ``row`` is the
    line number in the uploaded file (the header is line 1). Deliberately no
    password field — the report echoes everything about a row *except* its
    credential."""

    row: int
    display_name: str
    email: str | None
    role: str | None
    competition: str | None
    status: Literal["create", "skip", "error"]
    reason: str | None = None
    # The role half of the row: assigned, or skipped with a warning (actor
    # can't grant it / already held). None when the row carries no role.
    role_action: Literal["assign", "skip"] | None = None
    role_reason: str | None = None


class UserImportReport(BaseModel):
    """The full per-row report for both phases — ``dry_run`` preview and the
    commit — so the confirm screen and the final toast render the same shape."""

    dry_run: bool
    total: int
    created: int
    skipped: int
    errors: int
    roles_assigned: int
    roles_skipped: int
    # Header names present in the file but not part of the format — surfaced so
    # a typo'd optional column (``rolle``) is visible, not silently dropped.
    ignored_columns: list[str]
    rows: list[UserImportRowOut]
