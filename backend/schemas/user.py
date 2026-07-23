"""Admin user-management schemas (§7 — Users & Roles).

The account directory + create/edit surface an Administrator uses (gated on
``view_all_users`` / ``manage_users``). Distinct from ``schemas.auth.UserOut``
(a user's view of themselves after login) — this carries admin-only fields
(active/banned, whether they hold a global Administrator role).
"""

from datetime import datetime

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
