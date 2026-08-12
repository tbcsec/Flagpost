"""Singleton background scheduler process (#189 Phase 3, ADR-0025).

Under multi-worker the time-trigger scheduler must NOT run in every uvicorn
worker, or automations, the daily update check, and retention purge fire once
per worker. So it runs here as a single sidecar process alongside the web
workers (one container, started by docker-entrypoint.sh when WEB_CONCURRENCY>1);
the web workers skip it (see main.lifespan).

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
    # Relay (publish side) so scheduler-emitted broadcasts reach web-worker
    # clients. No-op unless multi-worker — but this process only runs then.
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
