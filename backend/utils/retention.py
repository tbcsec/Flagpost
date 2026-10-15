"""Archived-competition retention (#26).

Archiving is a reversible soft-close (§`Competition.archived_at`) — but an
instance accumulating dead archives retains their disk forever. When the site
setting ``archive_auto_delete`` is on, archiving stamps ``purge_after`` and the
per-minute scheduler (``utils/automation_scheduler``, kernel wiring) calls
:func:`purge_expired_competitions` to hard-delete any archived competition whose
clock has passed: attachment objects out of storage, then the tenant tree out of
the DB (§6.2 FK cascade), then ``competition.deleted`` (audit + automations see
a purge exactly like a manual delete, with ``auto: true``).

Grandfathering is structural: only the archive action ever sets ``purge_after``,
so competitions archived before the feature (or while the setting is off) have
NULL and are never touched. Unarchiving clears the clock; re-archiving restarts
it.

:func:`delete_competition_tree` is shared with the manual ``DELETE`` route — that
route previously cascaded the DB tree but orphaned the stored objects; now both
paths clean storage.
"""

from __future__ import annotations

import asyncio

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import ensure_aware_utc, utcnow
from models.attachment import Attachment
from models.judge_problem import JudgeProblem
from models.judging import CodeSubmission
from models.report import CompetitionReport
from models.competition import Competition
from models.ticket_attachment import TicketAttachment
from storage import get_storage
from storage.base import ObjectStorage
from utils.event_bus import event_bus

logger = logging.getLogger("retention")


def delete_objects(storage: ObjectStorage, keys) -> None:
    """Best-effort removal of stored objects (synchronous — call it through
    ``asyncio.to_thread``). An unreachable store must not block deleting the
    database rows; a leaked object is orphaned garbage, not a data leak."""
    for key in keys:
        try:
            storage.delete(key)
        except Exception:  # noqa: BLE001 — storage cleanup is best-effort
            logger.warning("could not delete stored object %s", key, exc_info=True)


async def delete_competition_tree(
    db: AsyncSession,
    storage: ObjectStorage,
    competition: Competition,
    *,
    actor_user_id: str | None = None,
    auto: bool = False,
) -> None:
    """Permanently delete a competition: attachment objects, then the DB tree.

    Storage deletes are best-effort per object — an unreachable/misconfigured
    store must not block reclaiming the database (§13.3 keys are namespaced per
    competition, so a leaked object is orphaned garbage, not a data leak).
    Commits, then emits ``competition.deleted`` (§3.2) so handlers only ever
    observe a durable deletion.
    """
    competition_id = competition.id
    # Every object-backed table — challenge files, ticket screenshots (#80), test data.
    object_keys = [
        *(
            await db.scalars(
                select(Attachment.object_key).where(
                    Attachment.competition_id == competition_id
                )
            )
        ).all(),
        *(
            await db.scalars(
                select(TicketAttachment.object_key).where(
                    TicketAttachment.competition_id == competition_id
                )
            )
        ).all(),
        # Programming problems' test-data zips (#447); null until a test case exists.
        *(
            key
            for key in (
                await db.scalars(
                    select(JudgeProblem.object_key).where(
                        JudgeProblem.competition_id == competition_id
                    )
                )
            ).all()
            if key
        ),
        # Submitted source code (#448).
        *(
            await db.scalars(
                select(CodeSubmission.source_object_key).where(
                    CodeSubmission.competition_id == competition_id
                )
            )
        ).all(),
        # Generated post-event report artefacts (#134): the PDF + HTML per report,
        # both nullable, so drop the empties.
        *(
            key
            for row in (
                await db.execute(
                    select(
                        CompetitionReport.pdf_object_key,
                        CompetitionReport.html_object_key,
                    ).where(CompetitionReport.competition_id == competition_id)
                )
            ).all()
            for key in row
            if key
        ),
    ]
    # Off the event loop: with code submissions this can be thousands of
    # synchronous round trips, and in a single-worker deployment the loop is
    # also the web server and the judge.
    await asyncio.to_thread(delete_objects, storage, object_keys)

    await db.delete(competition)
    await db.commit()
    await event_bus.emit(
        "competition.deleted",
        {"competition_id": competition_id, "user_id": actor_user_id, "auto": auto},
    )


async def purge_expired_competitions(
    db_factory,
    *,
    storage: ObjectStorage | None = None,
    now: datetime | None = None,
) -> int:
    """One retention tick: hard-delete every archived competition whose
    ``purge_after`` has passed. Returns how many were purged. Cheap no-op when
    nothing is due (one indexed-free select over the small competitions table).
    """
    now = ensure_aware_utc(now) if now is not None else utcnow()
    purged = 0
    async with db_factory() as db:
        candidates = (
            (
                await db.execute(
                    select(Competition).where(
                        # archived_at guards the invariant: only an *archived*
                        # competition may ever be purged, whatever purge_after says.
                        Competition.archived_at.is_not(None),
                        Competition.purge_after.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        # Compare in Python, like the lifecycle scheduler — sidesteps SQLite's
        # text-based datetime comparison (ADR-0006 dual-engine caution).
        due = [c for c in candidates if ensure_aware_utc(c.purge_after) <= now]
        for competition in due:
            name = competition.name
            try:
                await delete_competition_tree(
                    db, storage if storage is not None else get_storage(),
                    competition, auto=True,
                )
            except Exception:  # noqa: BLE001 — one bad row must not stop the rest
                logger.exception(
                    "failed to purge archived competition %s", competition.id
                )
                await db.rollback()
                continue
            purged += 1
            logger.info("purged archived competition %r (retention expired)", name)
    return purged
