"""Administrator-minted personal API tokens (issue #75).

An alternative to the browser JWT flow for programmatic REST access: an
administrator (``manage_api_tokens``) mints a token for a chosen user — the
token's **holder** — and it authenticates requests as that user with their
full effective permission set. Site-wide identity, like ``RefreshSession`` /
``PasswordResetToken`` — not ``CompetitionScopedMixin``. Only the SHA-256 of
the token is stored; the raw value is returned once, at creation.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin, UtcDateTime


class ApiToken(Base, TimestampMixin):
    __tablename__ = "api_tokens"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    # The token's holder — requests bearing this token authenticate as this user.
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # SHA-256 of the raw token; the raw value is only ever shown once, at mint time.
    token_hash: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )
    # Required, so tokens stay discernible in the admin list (per the issue).
    description: Mapped[str] = mapped_column(String, nullable=False)
    # Provenance — the minting administrator, like Achievement.awarded_by_user_id.
    # SET NULL (not CASCADE): deleting the admin who minted a token shouldn't
    # revoke the holder's still-valid token.
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
