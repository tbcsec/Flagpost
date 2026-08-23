"""Site-wide identity models: ``User`` and ``RefreshSession``.

``User`` and ``Role`` are the only entities that sit outside a competition
(§13.1), so neither uses ``CompetitionScopedMixin``. A user's *access* to a
given competition comes from ``RoleAssignment`` (see models/role.py), not from
the user row.

``RefreshSession`` makes refresh tokens revocable (ADR-0003 mandates the
httpOnly refresh cookie but is silent on revocation; a session row is what
"produces a current_user and a session" in §7.7 implies). Only the token's
hash is stored — the raw token lives solely in the client's httpOnly cookie.
"""

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin

# How long a user must wait between self-service username changes. Identity
# stability matters mid-event (the scoreboard, tickets and audit trail all show
# the name), so this is deliberately long. The admin rename bypasses the *check*
# but still stamps the clock (moderation, above).
USERNAME_CHANGE_COOLDOWN = timedelta(days=30)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    # The **display name is the primary login identifier** (a username): required
    # and case-insensitively unique (see the functional index below). Email is
    # **optional** — a user may sign in with their display name *or* their email,
    # so email is only a secondary handle. Unique-when-present (a UNIQUE column
    # permits multiple NULLs on both SQLite and Postgres).
    email: Mapped[str | None] = mapped_column(
        String, unique=True, index=True, nullable=True
    )
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    # Soft-ban (admin user management): a banned account can't log in and its
    # access is rejected at the auth dependency. Defaults active.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    # Per-user notification preferences (§4.4): a small bag of booleans keyed by
    # utils/notifications.DEFAULT_PREFS. Null = all defaults (a missing key
    # always resolves to its default), so an unset user opts into everything.
    notification_prefs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Email verification (issue #74): null = unverified. Set by the
    # /auth/verify-email token flow, or stamped at creation time for
    # admin-created accounts (Admin -> Users), which are exempt from the gate.
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Profile picture: stored in the DB like the site logo (not object storage)
    # so the additive backup (ADR-0016) carries it and the zero-infra dev stack
    # needs no MinIO. Always a server-re-encoded square WebP (utils/avatars) —
    # never the uploaded bytes. The blob is deferred so directory/auth queries
    # never drag image bytes; ``avatar_updated_at`` doubles as the "has an
    # avatar" flag and the client-side cache-buster.
    avatar_data: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True, deferred=True
    )
    avatar_content_type: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Self-service username (display name) change: when the name was last changed,
    # for the cooldown (null = never changed ⇒ no cooldown). Both the self and
    # admin paths stamp it — an admin rename that fixes an offensive name must
    # also start the clock, or the user could immediately rename back.
    username_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def username_change_allowed_at(self) -> datetime | None:
        """When the caller may next change their own username, or None if now.
        Read straight onto UserOut (from_attributes) so the profile UI can show
        the date before the user tries and is refused."""
        if self.username_changed_at is None:
            return None
        return self.username_changed_at + USERNAME_CHANGE_COOLDOWN


# Case-insensitive uniqueness for the login identifier: "Alice" and "alice" can't
# both exist, and login can match either casing. A functional index (portable
# across SQLite ≥3.9 and Postgres) rather than a plain UNIQUE, which would miss
# case variants. Declared at module level so it binds to the ORM column element.
Index("uq_users_display_name_lower", func.lower(User.display_name), unique=True)


class RefreshSession(Base, TimestampMixin):
    __tablename__ = "refresh_sessions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # SHA-256 of the raw refresh token; the raw value is never stored.
    token_hash: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
