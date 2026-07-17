"""Wildcard event-bus subscriber that persists every event to ``audit_log``.

This is the concrete Tier 0 consumer of the bus (ROADMAP #4): the mechanism
is built now, and the audit log is the only thing listening. ``competition_id``
and ``user_id`` are lifted out of the payload when present so the log is
queryable by tenant and actor without parsing JSON.
"""

from __future__ import annotations

import logging

from db import SessionLocal
from models.audit_log import AuditLogEntry
from utils.event_bus import EventPayload, event_bus

logger = logging.getLogger("audit_log")


@event_bus.on("*", owner="audit_log")
async def persist_event(event_name: str, payload: EventPayload) -> None:
    entry = AuditLogEntry(
        event_name=event_name,
        payload=payload,
        competition_id=payload.get("competition_id"),
        user_id=payload.get("user_id"),
    )
    async with SessionLocal() as session:
        session.add(entry)
        await session.commit()
    logger.debug("audit: recorded %s", event_name)


def register_audit_log() -> None:
    """Import side effect registers the subscriber; call to make intent explicit.

    Importing this module is what actually wires the handler (the decorator
    runs at import time); this no-op function exists so ``main.py`` can express
    "the audit log is now listening" as a call rather than a bare import.
    """
