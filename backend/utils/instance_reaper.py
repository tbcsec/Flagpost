"""Periodic reaper for challenge instances (#266, ADR-0036 §2).

Runs on the existing scheduler tick (``utils/automation_scheduler._loop``) —
no new process (ADR-0036 §2 rejected a dedicated instancer daemon). One pass
does four bounded jobs, each a cheap no-op when nothing is due:

1. **TTL expiry** — running instances past ``expires_at`` are torn down.
2. **Stuck provisioning** — a row still ``requested``/``provisioning`` long
   after it was created means the background task died; mark it ``failed``.
3. **Expiring retry** — a row left ``expiring`` by a destroy that failed is
   retried (``teardown`` is idempotent).
4. **Orphan GC** — backend containers with no live row are destroyed. Guarded
   by a *two-tick* rule: a container is only reaped if it looked orphaned on
   the previous pass too, so the brief window between ``create()`` returning
   and the row recording its handle can't cause a live instance to be killed.

Comparisons are done in Python (``ensure_aware_utc``) to sidestep SQLite's
text-datetime ordering, matching ``emit_lifecycle_events`` / retention.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from db import ensure_aware_utc, utcnow
from models.challenge_instancing import (
    INSTANCE_ACTIVE_STATUSES,
    SITE_BACKENDS,
    ChallengeInstance,
)
from utils.event_bus import event_bus
from utils.instance_service import load_settings, teardown, transition

logger = logging.getLogger(__name__)

# A provision that hasn't reached ``running`` this long after the row was
# created has lost its background task — provisioning is meant to take seconds.
STUCK_MINUTES = 5
# Bound the work one tick does, so a large backlog can't stall the shared
# scheduler; the next tick picks up the rest.
REAP_BATCH = 25

# Handles that looked orphaned on the previous tick (module-global, single
# process). The two-tick rule reaps only handles present in both this pass and
# the last, closing the create()→commit-handle race.
_orphan_seen: set[str] = set()


async def reap_instances(db_factory, *, now: datetime | None = None) -> None:
    """One reaper tick. Safe to call every scheduler interval; no-op when idle."""
    now = ensure_aware_utc(now) if now is not None else utcnow()

    # 1. TTL expiry — collect ids under a short read session, then tear down
    # (teardown opens its own sessions and is idempotent).
    async with db_factory() as db:
        running = (
            await db.execute(
                select(ChallengeInstance).where(
                    ChallengeInstance.status == "running",
                    ChallengeInstance.expires_at.is_not(None),
                )
            )
        ).scalars().all()
    due = [
        i.id
        for i in running
        if i.expires_at is not None and ensure_aware_utc(i.expires_at) <= now
    ][:REAP_BATCH]
    for instance_id in due:
        try:
            await teardown(db_factory, instance_id, event_name="challenge.instance_expired")
        except Exception:  # noqa: BLE001 — one bad row must not stop the pass
            logger.exception("TTL reap of instance %s failed", instance_id)

    # 2. Stuck provisioning → failed.
    cutoff = now - timedelta(minutes=STUCK_MINUTES)
    async with db_factory() as db:
        pending = (
            await db.execute(
                select(ChallengeInstance).where(
                    ChallengeInstance.status.in_(("requested", "provisioning"))
                )
            )
        ).scalars().all()
        stuck = [i for i in pending if ensure_aware_utc(i.created_at) <= cutoff][
            :REAP_BATCH
        ]
        failed_payloads = []
        for instance in stuck:
            transition(instance, "failed")
            instance.failure_reason = "provisioning timed out"
            failed_payloads.append(
                {
                    "competition_id": instance.competition_id,
                    "challenge_id": instance.challenge_id,
                    "instance_id": instance.id,
                    "user_id": instance.user_id,
                    "team_id": instance.team_id,
                }
            )
        if stuck:
            await db.commit()
    for payload in failed_payloads:
        await event_bus.emit("challenge.instance_provision_failed", payload)

    # 3. Expiring retry — a destroy that failed left the row expiring.
    async with db_factory() as db:
        expiring = (
            await db.execute(
                select(
                    ChallengeInstance.id, ChallengeInstance.expires_at
                ).where(ChallengeInstance.status == "expiring")
            )
        ).all()
    for instance_id, expires_at in list(expiring)[:REAP_BATCH]:
        # The first teardown that failed didn't emit, so reconstruct its intent:
        # a row past its TTL is an expiry; anything else was a manual destroy —
        # otherwise a TTL expiry that needed a retry would wrongly emit
        # instance_destroyed and automations keyed on instance_expired miss it.
        event = (
            "challenge.instance_expired"
            if expires_at is not None and ensure_aware_utc(expires_at) <= now
            else "challenge.instance_destroyed"
        )
        try:
            await teardown(db_factory, instance_id, event_name=event)
        except Exception:  # noqa: BLE001
            logger.exception("expiring-retry of instance %s failed", instance_id)

    # 4. Orphan GC (orchestrating backends only, when configured + enabled).
    await _reap_orphans(db_factory)


async def _reap_orphans(db_factory) -> None:
    global _orphan_seen
    async with db_factory() as db:
        settings = await load_settings(db)
        if (
            settings is None
            or not settings.enabled
            or settings.backend not in SITE_BACKENDS
        ):
            _orphan_seen = set()
            return
        live_handles = set(
            (
                await db.execute(
                    select(ChallengeInstance.backend_handle).where(
                        ChallengeInstance.status.in_(INSTANCE_ACTIVE_STATUSES),
                        ChallengeInstance.backend_handle.is_not(None),
                    )
                )
            ).scalars().all()
        )

    from utils.instance_service import provisioner_from_settings

    try:
        provisioner = provisioner_from_settings(settings)
        backend_handles = set(await provisioner.list())
    except Exception as exc:  # noqa: BLE001 — a listing failure just skips this pass
        logger.warning("orphan reap could not list instances: %s", exc)
        return

    orphans = backend_handles - live_handles
    # Two-tick rule: only reap handles that were also orphaned last pass.
    confirmed = orphans & _orphan_seen
    _orphan_seen = orphans
    for handle in list(confirmed)[:REAP_BATCH]:
        try:
            await provisioner.destroy(handle)
            logger.info("reaped orphan container %s (no live instance row)", handle)
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to reap orphan container %s: %s", handle, exc)
