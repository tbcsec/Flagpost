"""Pydantic schemas for attachments. ``object_key`` is deliberately never
exposed — clients get a signed URL, not the storage key (§13.3)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    challenge_id: str
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class SignedUrlOut(BaseModel):
    url: str
    expires_in_seconds: int
