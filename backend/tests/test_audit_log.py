"""The audit-log subscriber persists every emitted event (§3.3, ROADMAP #4)."""

from sqlalchemy import select

from db import SessionLocal
from models.audit_log import AuditLogEntry
from utils.audit_log import persist_event  # noqa: F401 - registers the subscriber
from utils.event_bus import event_bus


async def test_emitted_event_is_persisted():
    await event_bus.emit(
        "user.registered",
        {"user_id": "u-1", "email": "a@example.com"},
    )

    async with SessionLocal() as session:
        rows = (await session.execute(select(AuditLogEntry))).scalars().all()

    assert len(rows) == 1
    entry = rows[0]
    assert entry.event_name == "user.registered"
    assert entry.user_id == "u-1"
    assert entry.competition_id is None
    assert entry.payload["email"] == "a@example.com"


async def test_competition_id_is_lifted_from_payload():
    await event_bus.emit(
        "competition.created",
        {"competition_id": "c-1", "user_id": "u-1", "name": "Spring CTF"},
    )

    async with SessionLocal() as session:
        entry = (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.event_name == "competition.created"
                )
            )
        ).scalar_one()

    assert entry.competition_id == "c-1"
    assert entry.user_id == "u-1"
