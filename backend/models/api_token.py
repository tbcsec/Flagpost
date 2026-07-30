"""Personal API tokens (issue #75).

An alternative to the browser JWT flow for programmatic REST access. A token is
**self-minted and self-only**: a user creates one for their own account from
``/profile``, and it authenticates requests as them with their own effective
permission set. There is deliberately no way to mint a token *for* another
account — not even for an administrator — so no permission can become a route
to impersonating someone else.

Administrators holding ``manage_api_tokens`` get oversight, not issuance: they
can list every token and revoke any of them. Revocation only ever removes
access, so the permission can't escalate, while still making incident response
possible when a token leaks.

Site-wide identity, like ``RefreshSession`` / ``PasswordResetToken`` — not
``CompetitionScopedMixin``. Only the SHA-256 of the token is stored; the raw
value is returned once, at creation (ADR-0020 — hash what is only verified).
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
    # The token's holder *and* its creator: a token can only be minted by the
    # account it belongs to, so there is no separate provenance to record.
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # SHA-256 of the raw token; the raw value is only ever shown once, at mint time.
    token_hash: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )
    # Required, so tokens stay discernible in the holder's list and the admin
    # oversight view (per the issue).
    description: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
