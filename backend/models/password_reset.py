"""Password reset tokens (Phase 9, Group D — self-service reset, ADR-0003).

A short-lived, single-use token emailed to a user who forgot their password.
Only the SHA-256 of the token is stored (like ``RefreshSession``); the raw
value lives only in the emailed link. Site-wide identity, so not
``CompetitionScopedMixin``.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin, UtcDateTime


class PasswordResetToken(Base, TimestampMixin):
    __tablename__ = "password_reset_tokens"

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
