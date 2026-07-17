"""RBAC models: ``Role`` and ``RoleAssignment`` (ARCHITECTURE.md §7, ADR-0004).

Roles are rows, not a hardcoded enum — a role's capabilities are the
``permissions`` string array (keys from auth/permissions.py). The three
built-ins are seeded with ``is_system = True`` (§7.3): undeletable, and their
permission sets aren't directly editable, so "a Judge can always run their own
competition" stays a safe invariant.

``RoleAssignment`` binds a user to a role *per competition* (§7.5), except
global-scope roles (Administrator) which carry ``competition_id = None``.
"""

from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # "global" | "competition" (§7.1). Mirrors the scope of the permissions it
    # is expected to hold.
    scope: Mapped[str] = mapped_column(String, nullable=False)
    # Array of permission keys from the catalog (§7.2).
    permissions: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )


class RoleAssignment(Base, TimestampMixin):
    __tablename__ = "role_assignments"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "competition_id", "role_id", name="uq_role_assignment"
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # None only valid for a global-scope role (Administrator). Not the
    # CompetitionScopedMixin: an assignment can be site-wide.
    competition_id: Mapped[str | None] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    role_id: Mapped[str] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), index=True, nullable=False
    )
