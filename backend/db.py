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

from sqlalchemy import DateTime, ForeignKey, MetaData, TypeDecorator
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


class UtcDateTime(TypeDecorator):
    """A ``DateTime(timezone=True)`` that always returns **aware** UTC values.

    SQLite (tests/dev, ADR-0006) stores datetimes as text and drops tzinfo, so a
    naive value round-trips and then serializes to an offset-less ISO string
    that a browser misreads as local time. Coercing on load fixes it in one
    place — every timestamp leaves the API as aware UTC regardless of backend,
    so clients never have to compensate.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        return None if value is None else ensure_aware_utc(value)


class TimestampMixin:
    """Adds a ``created_at`` audit column."""

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, nullable=False
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


# pool_pre_ping validates a pooled connection at checkout and transparently
# replaces a dead one, so the first requests after a Postgres restart/failover/
# idle-kill don't 500; pool_recycle retires connections below common middlebox
# idle timeouts. Skipped for SQLite (the infra-free test/dev stack, ADR-0006),
# where a per-checkout ping on a local file DB is pointless.
def build_engine_kwargs(database_url: str) -> dict:
    """Pooling kwargs for ``create_async_engine`` (#174).

    SQLite (the infra-free test/dev stack, ADR-0006) gets none — a per-checkout
    ping on a local file DB is pointless and the pool-size knobs don't apply.
    Postgres gets pre-ping + recycle (survives restart/failover/idle-kill) plus
    an explicit pool bigger than SQLAlchemy's 5+10 default, which is the
    concurrency ceiling under load."""
    if database_url.startswith("sqlite"):
        return {}
    pool_size = settings.db_pool_size
    max_overflow = settings.db_max_overflow
    if settings.web_concurrency > 1:
        # Multi-worker (#189 Phase 3): the engine pool is per-process, so split a
        # fixed total budget across workers rather than letting N × 30 exhaust
        # Postgres max_connections. Overflow scales with the per-worker slice.
        pool_size = max(5, settings.db_connection_budget // settings.web_concurrency)
        max_overflow = max(5, pool_size // 2)
    return {
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_timeout": settings.db_pool_timeout,
    }


engine = create_async_engine(
    settings.database_url, future=True, **build_engine_kwargs(settings.database_url)
)
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
