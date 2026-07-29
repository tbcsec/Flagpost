"""Email verification tokens (issue #74 — admin-toggleable email verification).

A short-lived, single-use token emailed to a self-registered user so they can
confirm their address before joining a competition. Only the SHA-256 of the
token is stored (like ``PasswordResetToken``); the raw value lives only in the
emailed link. Site-wide identity, so not ``CompetitionScopedMixin``.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin, UtcDateTime


class EmailVerificationToken(Base, TimestampMixin):
    __tablename__ = "email_verification_tokens"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # SHA-256 of the raw token; the raw value is only ever in the emailed link.
    token_hash: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
