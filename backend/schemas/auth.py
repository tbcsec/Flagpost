"""Pydantic request/response schemas for auth (kept separate from models)."""

from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    # Display name is the primary identifier (a username); email is optional.
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=256)
    email: EmailStr | None = None


class LoginRequest(BaseModel):
    # Accepts the display name (username) *or* the email address. The ``email``
    # JSON alias is kept for back-compat with older clients.
    identifier: str = Field(
        validation_alias=AliasChoices("identifier", "email"),
        min_length=1,
        max_length=320,
    )
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr | None
    display_name: str
    created_at: datetime


class PermissionsOut(BaseModel):
    """The caller's effective permissions, split global vs per-competition.

    The client's effective set for a competition is ``global ∪
    by_competition[id]``. The field is emitted as ``global`` (a Python keyword,
    hence the alias)."""

    model_config = ConfigDict(populate_by_name=True)

    global_perms: list[str] = Field(serialization_alias="global")
    by_competition: dict[str, list[str]]


class TokenResponse(BaseModel):
    """The access token plus the authenticated user.

    The refresh token is NOT in the body — it's set as an httpOnly cookie
    (ADR-0003), so it never touches JS-readable storage.
    """

    access_token: str
    token_type: str = "bearer"
    user: UserOut
