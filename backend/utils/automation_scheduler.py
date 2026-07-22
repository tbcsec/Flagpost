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
from datetime import datetime

from sqlalchemy import select

from db import ensure_aware_utc, utcnow
from models.automation import AutomationRule
from models.competition import Competition
from plugins.loader import is_module_enabled
from utils.automation_engine import evaluate_conditions, run_rule

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
    while True:
        try:
            await run_time_rules(db_factory)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a bad tick must not kill the loop
            logger.exception("time-rule scheduler tick failed")
        await asyncio.sleep(interval_seconds)
