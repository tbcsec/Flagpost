"""Singleton background scheduler process (#189 Phase 3, ADR-0025, ADR-0031).

The time-trigger scheduler must run in exactly ONE process per deployment, or
automations, the daily update check, and retention purge fire once per copy
(job pickup has no cross-process claim locking). Two ways this process is that
one:

- **Sidecar** (single container, ADR-0025): started by docker-entrypoint.sh
  when WEB_CONCURRENCY>1, alongside the web workers, which skip it
  (see main.lifespan).
- **Dedicated service** (multi-instance, ADR-0031): one task/container runs
  ``python -m scheduler`` while every web task sets SCHEDULER_ENABLED=false.
  Give this service ``MULTI_INSTANCE=1`` (+ REDIS_URL) too, so the relay
  below attaches and its broadcasts reach the web tasks' clients.

Deliberately **ignores SCHEDULER_ENABLED** — running this module is the
explicit opt-in the flag exists to gate elsewhere.

Importing ``main`` gives this process the same wiring the web app has —
audit-log subscriber, WS eviction, event catalog, and all plugin modules
(``load_modules`` runs at import) — so events the scheduler emits are audited
and handled exactly as in a web worker. It attaches the broadcast relay (publish
side) so scheduler-emitted broadcasts reach clients on the web workers; it has
no sockets of its own, so the presence heartbeat it also starts is a harmless
no-op. It never serves HTTP/WS.
"""

from __future__ import annotations

import asyncio
import logging

import main  # noqa: F401 — import side effects: audit + eviction + plugin wiring
from config import settings
from db import SessionLocal
from realtime import start_realtime, stop_realtime
from utils import automation_scheduler

logger = logging.getLogger("scheduler")


async def run() -> None:
    logger.info("scheduler sidecar starting (singleton time-trigger process)")
    # Relay (publish side) so scheduler-emitted broadcasts reach web-worker /
    # web-task clients. Engages when WEB_CONCURRENCY>1 (sidecar mode) or
    # MULTI_INSTANCE=1 (dedicated-service mode, ADR-0031); a lone single-worker
    # deployment never runs this process at all.
    await start_realtime()
    automation_scheduler.start(
        SessionLocal, settings.automation_scheduler_interval_seconds
    )
    stop = asyncio.Event()
    try:
        await stop.wait()  # run until the process is signalled
    finally:
        automation_scheduler.stop()
        await stop_realtime()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
