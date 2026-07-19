"""Async database plumbing.

The single async engine, session factory, declarative ``Base``, and the
``get_db`` FastAPI dependency all live here. Every model imports ``Base`` from
this module so Alembic autogenerate sees one metadata object.

Multi-tenancy note (ARCHITECTURE.md §6.2, ADR-0001): tenant-scoped tables mix
in :class:`CompetitionScopedMixin` so they all carry a non-null
``competition_id`` FK. App-level scoping is only as strong as every query
applying it — the mixin makes "does this table belong to a competition"
answerable structurally rather than per-table guesswork.
"""

from collections.abc import AsyncIterator
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, MetaData
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config import settings

# Predictable constraint names so Alembic autogenerate produces stable,
# reviewable migrations (and batch ops on SQLite in tests work).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    """Timezone-aware UTC now. Used as a column default across models."""
    return datetime.now(timezone.utc)


def ensure_aware_utc(dt: datetime) -> datetime:
    """Coerce a possibly-naive datetime to timezone-aware UTC.

    Postgres round-trips ``DateTime(timezone=True)`` as aware, but SQLite (used
    in tests, ADR-0006) drops tzinfo. Normalising on read keeps datetime
    comparisons portable across both backends.
    """
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class TimestampMixin:
    """Adds a ``created_at`` audit column."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class CompetitionScopedMixin:
    """Every tenant-scoped table carries a non-null ``competition_id`` (§6.2).

    Site-wide entities (``User``, ``Role``) deliberately do NOT use this mixin;
    everything below ``Competition`` in the domain model (§13.1) does.
    """

    competition_id: Mapped[str] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


engine = create_async_engine(settings.database_url, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

if engine.dialect.name == "sqlite":
    # SQLite ships with foreign keys OFF; enable them so the test suite
    # (ADR-0006) enforces the same CASCADE / SET NULL semantics Postgres does.
    from sqlalchemy import event as _sa_event

    @_sa_event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_fks(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped async session."""
    async with SessionLocal() as session:
        yield session
