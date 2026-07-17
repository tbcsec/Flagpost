"""Pydantic request/response schemas for auth (kept separate from models)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    display_name: str
    created_at: datetime


class TokenResponse(BaseModel):
    """The access token plus the authenticated user.

    The refresh token is NOT in the body — it's set as an httpOnly cookie
    (ADR-0003), so it never touches JS-readable storage.
    """

    access_token: str
    token_type: str = "bearer"
    user: UserOut
