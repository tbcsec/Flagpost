"""Time-based automation trigger (ARCHITECTURE.md §5.2).

The automation engine is otherwise a pure event-bus consumer, but "N minutes
before a competition ends" has no mutation to hang an event off — it's a
*clock* condition. This is the one scheduled trigger: a periodic tick evaluates
rules whose ``trigger_type`` is ``competition.time_remaining`` against the live
minutes-remaining of their competition, and fires each **once**, when its
condition first goes true (edge-triggered).

Design choices:

- **Competition-scoped only.** A time rule fires for exactly one competition
  (`competition_id` set); a global time rule would need per-competition dedup,
  so the tick simply skips global ones. This matches the use — "open *this*
  competition's survey an hour before it ends".
- **Fire-once via ``trigger_count``.** The tick only considers rules with
  ``trigger_count == 0``; ``run_rule`` bumps it, so the next tick excludes a
  rule that already fired. No separate state table, and it survives the
  process (the count is persisted) — unlike a purely in-memory milestone set.
- **The condition is the threshold.** A rule adds a normal condition like
  ``minutes_remaining <= 60``; the tick computes ``minutes_remaining`` into the
  payload and reuses the engine's condition evaluation. Any threshold works,
  and ``{minutes_remaining}`` is available to action templates.

Single-process, like the rest of the runtime (ADR-0005). Started/stopped by
``main.py``'s lifespan (kernel wiring, alongside the audit-log consumer); the
tick is a no-op when there are no time rules, so it costs a cheap query a minute.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import or_, select

from config import settings
from db import ensure_aware_utc, utcnow
from models.announcement import Announcement
from models.automation import AutomationRule
from models.certificate import CertificateExportJob, CertificateTemplate
from models.competition import Competition
from models.hint import Hint
from plugins.loader import is_module_enabled
from utils.automation_engine import evaluate_conditions, run_rule
from utils.certificate_release import (
    build_recipients,
    gather_image_bytes,
    load_custom_font_bytes,
    release_template,
    spec_from_template,
)
from utils.event_bus import event_bus
from utils.notifications import broadcast_notifications

logger = logging.getLogger("automation")

TRIGGER = "competition.time_remaining"

_task: asyncio.Task | None = None


async def run_time_rules(db_factory, *, now: datetime | None = None) -> None:
    """One scheduler tick: fire every competition-scoped, not-yet-fired time
    rule whose threshold condition is now met. Idempotent per rule."""
    now = ensure_aware_utc(now) if now is not None else utcnow()
    async with db_factory() as db:
        rules = (
            (
                await db.execute(
                    select(AutomationRule).where(
                        AutomationRule.trigger_type == TRIGGER,
                        AutomationRule.is_enabled.is_(True),
                        AutomationRule.owner_user_id.is_(None),
                        AutomationRule.competition_id.is_not(None),
                        AutomationRule.trigger_count == 0,
                    )
                )
            )
            .scalars()
            .all()
        )
        for rule in rules:
            competition = await db.get(Competition, rule.competition_id)
            if competition is None or competition.end_at is None:
                continue
            end_at = ensure_aware_utc(competition.end_at)
            if now >= end_at:
                continue  # already ended — nothing to count down to
            # Respect the per-competition module toggle (§11.3).
            if not await is_module_enabled(db, "automations", rule.competition_id):
                continue
            minutes_remaining = int((end_at - now).total_seconds() // 60)
            payload = {
                "competition_id": rule.competition_id,
                "minutes_remaining": minutes_remaining,
            }
            if evaluate_conditions(rule.conditions, payload):
                await run_rule(db, rule, TRIGGER, payload)


async def emit_lifecycle_events(db_factory, *, now: datetime | None = None) -> None:
    """Emit ``competition.started`` / ``competition.ended`` once each, when a
    competition's ``start_at`` / ``end_at`` is reached (§3.2 lifecycle triggers).
    Dedup persists via the ``*_event_fired`` flags so a restart can't double-fire.
    Emitted for **audit** regardless of the automations module — the engine gates
    on the module per-rule."""
    now = ensure_aware_utc(now) if now is not None else utcnow()
    to_emit: list[tuple[str, dict]] = []
    async with db_factory() as db:
        competitions = (
            (
                await db.execute(
                    select(Competition).where(
                        Competition.archived_at.is_(None),
                        or_(
                            Competition.started_event_fired.is_(False),
                            Competition.ended_event_fired.is_(False),
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        for c in competitions:
            if (
                not c.started_event_fired
                and c.start_at is not None
                and now >= ensure_aware_utc(c.start_at)
            ):
                c.started_event_fired = True
                # Auto-open the gate (#221), but never override a manual stop that
                # already moved it past not_started.
                if c.status == "not_started":
                    c.status = "running"
                to_emit.append(
                    ("competition.started", {"competition_id": c.id, "name": c.name})
                )
            if (
                not c.ended_event_fired
                and c.end_at is not None
                and now >= ensure_aware_utc(c.end_at)
            ):
                c.ended_event_fired = True
                c.status = "ended"  # scheduled end closes the gate (#221)
                to_emit.append(
                    ("competition.ended", {"competition_id": c.id, "name": c.name})
                )
        if to_emit:
            await db.commit()
    # Emit after commit so the fired flag is durable before any handler runs.
    for name, payload in to_emit:
        await event_bus.emit(name, payload)


async def publish_scheduled_hints(db_factory, *, now: datetime | None = None) -> None:
    """Publish every hidden hint whose scheduled ``release_at`` has arrived
    (#213): flip it visible and emit ``hint.published`` (what the release
    automations subscribe to). Idempotent — once unhidden a hint no longer
    matches. Compared in Python like the lifecycle tick, for tz correctness
    across SQLite/Postgres. Fires for audit regardless of the module toggle;
    the engine gates any rule on the module per-rule."""
    now = ensure_aware_utc(now) if now is not None else utcnow()
    to_emit: list[dict] = []
    async with db_factory() as db:
        hints = (
            (
                await db.execute(
                    select(Hint).where(
                        Hint.hidden.is_(True),
                        Hint.release_at.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for hint in hints:
            if now >= ensure_aware_utc(hint.release_at):
                hint.hidden = False
                to_emit.append(
                    {
                        "competition_id": hint.competition_id,
                        "challenge_id": hint.challenge_id,
                        "hint_id": hint.id,
                    }
                )
        if to_emit:
            await db.commit()
    # Emit after commit so the unhide is durable before any handler runs.
    for payload in to_emit:
        await event_bus.emit("hint.published", payload)


async def publish_scheduled_announcements(
    db_factory, *, now: datetime | None = None
) -> None:
    """Publish every scheduled announcement whose ``publish_at`` has arrived
    (#349): flip it visible and emit ``announcement.published`` — the *same* event
    an immediate post emits, so the announcements module delivers it (WS broadcast
    + bell notifications) identically. Idempotent — once unhidden a row no longer
    matches. Compared in Python like the hint tick, for tz correctness across
    SQLite/Postgres. The payload mirrors the route's exactly."""
    now = ensure_aware_utc(now) if now is not None else utcnow()
    to_emit: list[dict] = []
    async with db_factory() as db:
        announcements = (
            (
                await db.execute(
                    select(Announcement).where(
                        Announcement.hidden.is_(True),
                        Announcement.publish_at.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for announcement in announcements:
            if now >= ensure_aware_utc(announcement.publish_at):
                announcement.hidden = False
                to_emit.append(
                    {
                        "competition_id": announcement.competition_id,
                        "announcement_id": announcement.id,
                        "title": announcement.title,
                        "body": announcement.body,
                        "severity": announcement.severity,
                        "audience_type": announcement.audience_type,
                        "created_at": announcement.created_at.isoformat(),
                    }
                )
        if to_emit:
            await db.commit()
    # Emit after commit so the unhide is durable before any handler runs.
    for payload in to_emit:
        await event_bus.emit("announcement.published", payload)


async def release_scheduled_certificates(db_factory, *, now: datetime | None = None) -> None:
    """Release every certificate template whose scheduled time has arrived (#219):
    ``on_end`` at the competition's end, ``end_delay`` at end + N minutes. Sets
    ``released_at``, notifies every recipient, and emits ``certificate.released``.
    Idempotent via the ``released_at IS NULL`` guard. Skipped when the module is
    disabled for the competition — a disabled module shows no certificates, so
    releasing + deep-linking a participant to a 404 would be wrong."""
    now = ensure_aware_utc(now) if now is not None else utcnow()
    released: list[tuple[str, str, list]] = []  # (template_id, competition_id, notifications)
    async with db_factory() as db:
        templates = (
            (
                await db.execute(
                    select(CertificateTemplate).where(
                        CertificateTemplate.released_at.is_(None),
                        CertificateTemplate.release_mode.in_(("on_end", "end_delay")),
                    )
                )
            )
            .scalars()
            .all()
        )
        for template in templates:
            competition = await db.get(Competition, template.competition_id)
            if competition is None or competition.end_at is None:
                continue
            target = ensure_aware_utc(competition.end_at)
            if template.release_mode == "end_delay":
                target = target + timedelta(minutes=template.release_delay_minutes)
            if now < target:
                continue
            if not await is_module_enabled(db, "certificates", template.competition_id):
                continue
            made = await release_template(db, competition, template, now=now)
            if made is not None:  # None ⇒ a concurrent caller already released it
                released.append((template.id, template.competition_id, made))
        if released:
            await db.commit()
    # Broadcast + emit after commit so the release is durable before any handler.
    for template_id, competition_id, made in released:
        await broadcast_notifications(made)
        await event_bus.emit(
            "certificate.released",
            {"competition_id": competition_id, "certificate_template_id": template_id},
        )


# A single bulk export renders one PNG per recipient into one in-memory ZIP; cap
# it so one click on a huge competition can't pin a core + spike RAM unboundedly.
# Batched/streamed export for very large events is a follow-up (#219).
MAX_EXPORT_RECIPIENTS = 3000
# A job left "running" past this (a worker that died mid-render) is reclaimed as
# failed so the organiser's poll doesn't hang forever.
EXPORT_STUCK_MINUTES = 15


def _render_export_zip(spec: dict, recipients: list, bg_bytes, images, fonts, branding) -> tuple[bytes, int]:
    """Pure (no DB/ORM): render every recipient's PNG into a ZIP. Runs in a
    worker thread — Pillow is CPU-bound and must not block the event loop. A
    single recipient's failure is skipped (logged), never aborting the whole ZIP.
    Returns (zip_bytes, rendered_count)."""
    import io
    import zipfile

    from plugins.certificates.render import render_certificate_png

    rendered = 0
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, r in enumerate(recipients):
            try:
                png = render_certificate_png(
                    spec,
                    r.tokens,
                    background_bytes=bg_bytes,
                    image_bytes=images,
                    font_bytes=fonts,
                    branding=branding,
                )
            except Exception:
                logger.exception("certificate export: recipient %s render failed", r.user_id)
                continue
            safe = "".join(c if (c.isalnum() or c in "-_ ") else "_" for c in r.user_name).strip()
            zf.writestr(f"{i + 1:04d}-{safe or 'certificate'}.png", png)
            rendered += 1
    return buf.getvalue(), rendered


async def process_certificate_exports(db_factory) -> None:
    """Render one pending bulk-export job into a ZIP in object storage (#219).
    One job per tick bounds the work; the ORM stays out of the render thread —
    the spec + resolved image bytes are extracted first, then handed to a pure
    builder."""
    async with db_factory() as db:
        # Reclaim jobs a dead worker left stuck "running" (the tick awaits each
        # render fully, so a live process never carries one across ticks).
        stuck = (
            await db.execute(
                select(CertificateExportJob).where(
                    CertificateExportJob.status == "running",
                    CertificateExportJob.created_at
                    < utcnow() - timedelta(minutes=EXPORT_STUCK_MINUTES),
                )
            )
        ).scalars().all()
        for s in stuck:
            s.status = "failed"
            s.error = "Export timed out"
            s.completed_at = utcnow()
        if stuck:
            await db.commit()

        job = await db.scalar(
            select(CertificateExportJob)
            .where(CertificateExportJob.status == "pending")
            .order_by(CertificateExportJob.created_at)
            .limit(1)
        )
        if job is None:
            return
        job.status = "running"
        await db.commit()
        try:
            competition = await db.get(Competition, job.competition_id)
            template = await db.scalar(
                select(CertificateTemplate).where(
                    CertificateTemplate.competition_id == job.competition_id
                )
            )
            if competition is None or template is None:
                raise RuntimeError("competition or template no longer exists")
            recipients = await build_recipients(db, competition, template)
            if len(recipients) > MAX_EXPORT_RECIPIENTS:
                raise RuntimeError(
                    f"Too many recipients ({len(recipients)}) for a single export; "
                    f"the limit is {MAX_EXPORT_RECIPIENTS}."
                )
            job.total = len(recipients)
            await db.commit()

            from storage import get_storage

            storage = get_storage()
            # Shared spec/asset resolution so the ZIP renders identically to the
            # single self-download — background (incl. preset accent/base overrides),
            # image elements, and any custom fonts.
            spec = spec_from_template(template)
            bg_bytes = None
            if spec["background_kind"] == "upload" and spec["background_object_key"]:
                try:
                    bg_bytes = storage.get(spec["background_object_key"])
                except Exception:
                    bg_bytes = None
            images = gather_image_bytes(storage, spec["elements"], job.competition_id)
            font_bytes = await load_custom_font_bytes(
                db, storage, job.competition_id, spec["elements"]
            )
            branding = not settings.certificate_branding_removable
            data, rendered = await asyncio.to_thread(
                _render_export_zip, spec, recipients, bg_bytes, images, font_bytes, branding
            )
            key = f"{job.competition_id}/certificates/exports/{job.id}.zip"
            await asyncio.to_thread(storage.put, key, data, "application/zip")
            job.object_key = key
            job.rendered = rendered
            job.status = "done"
            job.completed_at = utcnow()
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — a bad job must not kill the loop
            logger.exception("certificate export %s failed", job.id)
            job.status = "failed"
            job.error = str(exc)[:500]
            job.completed_at = utcnow()
            await db.commit()


REPORT_STUCK_MINUTES = 15


async def process_report_jobs(db_factory) -> None:
    """Render one pending post-event report per tick (#134, ADR-0030): build its
    data, render HTML/PDF off the event loop, store the artefacts, mark it ready,
    and emit ``report.generated``. Mirrors ``process_certificate_exports`` — one
    job per tick, stuck-job reclamation, a failure is recorded not raised."""
    from models.competition import Competition
    from models.report import CompetitionReport
    from plugins.reports import render
    from storage import get_storage
    from utils.event_bus import event_bus
    from utils.report_data import SECTIONS, build_report_data

    storage = get_storage()
    async with db_factory() as db:
        stuck = (
            await db.execute(
                select(CompetitionReport).where(
                    CompetitionReport.status == "running",
                    CompetitionReport.created_at
                    < utcnow() - timedelta(minutes=REPORT_STUCK_MINUTES),
                )
            )
        ).scalars().all()
        for s in stuck:
            s.status = "failed"
            s.error = "Report render timed out"
            s.completed_at = utcnow()
        if stuck:
            await db.commit()

        report = await db.scalar(
            select(CompetitionReport)
            .where(CompetitionReport.status == "pending")
            .order_by(CompetitionReport.created_at)
            .limit(1)
        )
        if report is None:
            return
        report.status = "running"
        await db.commit()
        report_id = report.id
        competition_id = report.competition_id

        stored_keys: list[str] = []
        try:
            competition = await db.get(Competition, competition_id)
            if competition is None:
                raise RuntimeError("competition no longer exists")
            cfg = report.config or {}
            sections = cfg.get("sections") or list(SECTIONS)
            formats = tuple(cfg.get("formats") or ("pdf", "html"))
            options = cfg.get("options") or {}
            data = await build_report_data(
                db, competition, sections=sections, options=options
            )
            branding = await render.fetch_branding(db)
            artefacts = await asyncio.to_thread(
                render.render_report,
                data,
                branding,
                generated_at=utcnow(),
                formats=formats,
            )
            # Track the key BEFORE the put, so a put that durably writes then
            # raises (a network flake after the object lands) is still cleaned up.
            if "pdf" in artefacts:
                key = f"{competition_id}/reports/{report_id}.pdf"
                stored_keys.append(key)
                await asyncio.to_thread(
                    storage.put, key, artefacts["pdf"], "application/pdf"
                )
                report.pdf_object_key = key
            if "html" in artefacts:
                key = f"{competition_id}/reports/{report_id}.html"
                stored_keys.append(key)
                await asyncio.to_thread(
                    storage.put,
                    key,
                    artefacts["html"].encode("utf-8"),
                    "text/html; charset=utf-8",
                )
                report.html_object_key = key
            report.status = "ready"
            report.completed_at = utcnow()
            await db.commit()
            await event_bus.emit(
                "report.generated",
                {
                    "competition_id": competition_id,
                    "report_id": report_id,
                    "version": report.version,
                    "user_id": report.requested_by,
                },
            )
        except Exception as exc:  # noqa: BLE001 — a bad job must not kill the loop
            logger.exception("report %s render failed", report_id)
            # Roll back the failed transaction, drop any objects stored this run,
            # then record the failure — but re-fetch first so a competition deleted
            # mid-render (its report row cascade-gone) can't crash the whole tick on
            # a commit against a row that no longer exists.
            await db.rollback()
            for key in stored_keys:
                try:
                    await asyncio.to_thread(storage.delete, key)
                except Exception:  # noqa: BLE001 — cleanup is best-effort
                    logger.warning("could not clean up report object %s", key)
            fresh = await db.get(CompetitionReport, report_id)
            if fresh is not None:
                fresh.status = "failed"
                fresh.error = str(exc)[:500]
                fresh.completed_at = utcnow()
                await db.commit()


def runs_in_process(app_settings=settings) -> bool:
    """Should THIS web process start the scheduler in its lifespan (ADR-0031)?

    Single-worker only — multi-worker runs the entrypoint's sidecar instead —
    and only when the deployment hasn't delegated scheduling to a dedicated
    ``python -m scheduler`` service (``SCHEDULER_ENABLED=false`` on the web
    tasks of a multi-instance topology). Job pickup has no cross-process claim
    locking, so the deployment must arrange for exactly one scheduler.
    """
    return app_settings.scheduler_enabled and app_settings.web_concurrency <= 1


def start(db_factory, interval_seconds: float) -> None:
    """Launch the periodic tick (idempotent). Requires a running event loop."""
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.ensure_future(_loop(db_factory, interval_seconds))


def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None


async def _loop(db_factory, interval_seconds: float) -> None:
    # Imported here, not at module top: retention pulls in the storage layer,
    # which the pure rule-evaluation imports above shouldn't drag along.
    from utils.instance_reaper import reap_instances
    from utils.retention import purge_expired_competitions
    from utils.update_check import run_check

    while True:
        try:
            await emit_lifecycle_events(db_factory)
            await run_time_rules(db_factory)
            await publish_scheduled_hints(db_factory)
            # Scheduled announcement release (#349) rides the same kernel tick as
            # scheduled hints; a cheap no-op when nothing is due.
            await publish_scheduled_announcements(db_factory)
            # Scheduled certificate release + bulk-export processing (#219) ride
            # the same kernel tick; both are no-ops when nothing is due/pending.
            await release_scheduled_certificates(db_factory)
            await process_certificate_exports(db_factory)
            # Post-event report rendering (#134) rides the same tick; a no-op when
            # no report is pending.
            await process_report_jobs(db_factory)
            # Archived-competition retention (#26) rides the same kernel tick —
            # platform housekeeping like the lifecycle events, active
            # regardless of any per-competition module toggle.
            await purge_expired_competitions(db_factory)
            # Challenge-instance reaping (#266, ADR-0036): TTL expiry, stuck
            # provisions, and orphan containers. Rides the same tick and is a
            # cheap no-op when no instances exist / instancing isn't configured.
            await reap_instances(db_factory)
            # Update check + adoption count (#111). Self-rate-limiting to once
            # a day off its own persisted timestamps, so calling it every tick
            # costs one row read that almost always returns immediately.
            await run_check(db_factory)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a bad tick must not kill the loop
            logger.exception("time-rule scheduler tick failed")
        await asyncio.sleep(interval_seconds)
