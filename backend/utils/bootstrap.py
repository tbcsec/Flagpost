"""Boot-time baseline import (#357, ADR-0038).

When ``BOOTSTRAP_BACKUP_FILE`` points at a platform export (ADR-0016), a fresh
— *unconfigured* — instance imports it on startup instead of coming up empty:
the file provisions the owner, branding, competitions and users declaratively.

Gated on the first-run setup state, so a normal install imports exactly once
(the next boot sees an administrator and skips), while an internal demo that
resets to a baseline on a schedule re-imports on every clean boot. A set-but-
unreadable or invalid file aborts startup rather than silently booting empty —
the same refuse-to-start posture as the metrics gate.

Trust model: the import runs with ``actor=None``, which skips the grant-
containment guard (a bound on *API* callers' privilege escalation). That's
correct here — the file comes from the operator's filesystem, the same trust
root as ``JWT_SECRET_FILE`` and ``DATABASE_URL``; whoever can mount it already
owns the instance. See ADR-0038.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from auth.setup import instance_needs_setup, mark_setup_complete
from config import settings
from storage.base import ObjectStorage
from utils import backup
from utils.event_bus import event_bus

logger = logging.getLogger("startup")

# A fixed key for the Postgres advisory lock that serialises the import across
# workers/instances (see below). Arbitrary but stable and feature-specific.
_BOOTSTRAP_LOCK_KEY = 0x_F1A6_B007  # "flagpost boot"


class BootstrapError(RuntimeError):
    """A configured baseline import could not be applied — abort startup."""


async def run_bootstrap_import(
    db: AsyncSession, storage: ObjectStorage | None = None
) -> bool:
    """Import the configured baseline into an unconfigured instance.

    Returns True if an import was applied, False if it was a no-op (feature off
    or the instance is already provisioned). Raises :class:`BootstrapError` on a
    configured-but-unusable file, which the lifespan lets abort startup.
    """
    path = settings.bootstrap_backup_file.strip()
    if not path:
        return False  # feature off

    # Only ever import into an unconfigured instance. On a normal install this
    # is the first boot; on a reset-on-a-schedule demo every clean boot is
    # fresh, so the baseline re-applies. An already-owned instance is left
    # exactly as-is — a populated additive import is not a reset.
    if not await instance_needs_setup(db):
        logger.info(
            "BOOTSTRAP_BACKUP_FILE set but an administrator already exists — "
            "skipping baseline import (instance already provisioned)."
        )
        return False

    # Serialise the import across processes. Under WEB_CONCURRENCY>1 (or several
    # ADR-0031 instances against one Postgres) every worker's lifespan runs this,
    # and the gate above is a check-then-act: without a lock they would all pass
    # it and import concurrently, racing unique constraints (crashed workers) and
    # duplicating rows with no unique key (e.g. Competition.name). A transaction-
    # scoped Postgres advisory lock lets exactly one worker import; the rest block,
    # then re-check and skip. SQLite (the test suite and the single-worker default)
    # is single-process + single-writer, so it needs none — mirrors why the
    # scheduler runs single-instance (automation_scheduler.runs_in_process).
    from db import engine

    if engine.dialect.name == "postgresql":
        from sqlalchemy import text

        await db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": _BOOTSTRAP_LOCK_KEY}
        )
        if not await instance_needs_setup(db):
            await db.rollback()  # end the txn to release the lock for other workers
            logger.info(
                "Baseline already imported by another worker — skipping (%s).", path
            )
            return False

    try:
        with open(path, "rb") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        raise BootstrapError(
            f"BOOTSTRAP_BACKUP_FILE {path!r} could not be read as a Flagpost "
            f"export ({exc}). Fix or unset it — refusing to start empty."
        ) from exc

    try:
        if storage is None:
            # Constructed lazily, only once we know we're importing — the no-op
            # paths above never need object storage (and thus never MinIO).
            from storage import get_storage

            storage = get_storage()
        # import_data commits once at the end, so a failure here leaves the DB
        # untouched rather than half-imported. All sections; actor=None (trust
        # model above).
        result = await backup.import_data(
            db, storage, payload, list(backup.SECTIONS), actor=None
        )
    except Exception as exc:
        # Any failure to apply a configured baseline must refuse to start, with
        # operator-facing context — not escape as a bare traceback. Covers the
        # import engine's own errors, an unexpected IntegrityError, and object-
        # storage connection failures alike.
        raise BootstrapError(
            f"Baseline import from {path!r} failed: {exc}"
        ) from exc

    created = sum(counts["created"] for counts in result.values())

    # The import cannot set ``setup_completed_at`` — it's import-immutable (the
    # F2 hardening), so a baseline that provisioned an owner must mark setup
    # complete itself, the invariant every owner-provisioning path upholds
    # (#133). Without this the setup wizard would correctly refuse yet the
    # SetupGuard would still redirect every visitor to it.
    provisioned_owner = not await instance_needs_setup(db)
    if provisioned_owner:
        await mark_setup_complete(db)
        await db.commit()
    else:
        # No *active* administrator resulted (none in the file, or the only one
        # imported soft-banned): the instance stays unconfigured, so the wizard
        # stays open and — with the file still mounted — this import re-runs each
        # boot. Say so loudly rather than leave a silent dead-end.
        logger.warning(
            "Baseline import from %s created %d records but provisioned no active "
            "administrator — the instance remains unconfigured. Complete /setup, "
            "or fix the baseline so it carries an active owner.",
            path,
            created,
        )

    # Commit-before-emit: import_data and the mark above have committed, so the
    # audit consumer's own session won't deadlock on the writer lock. Announce
    # only a bootstrap that actually provisioned the instance — a no-owner
    # baseline re-runs every boot (the site_settings singleton always counts as
    # "created"), and must not spam the audit-logged event each time.
    if provisioned_owner:
        await event_bus.emit(
            "platform.imported",
            {
                "user_id": None,
                "sections": list(backup.SECTIONS),
                "created": created,
                "source": "bootstrap",
            },
        )
    logger.info(
        "Baseline import from %s applied: %d records created%s.",
        path,
        created,
        "" if provisioned_owner else " (no active owner — instance still needs setup)",
    )
    return True
