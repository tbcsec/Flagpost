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

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin


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
