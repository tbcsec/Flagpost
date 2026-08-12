"""FastAPI entrypoint.

Wires the audit-log event subscriber and mounts one router per domain
(ARCHITECTURE.md §14). The hello/health endpoints from the Tier 0 skeleton
remain as a liveness/connectivity check.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from auth.seed import seed_system_roles
from config import settings
from db import SessionLocal
from plugins.loader import load_modules
from realtime import router as realtime_router
from realtime import start_realtime, stop_realtime
from realtime.eviction import register_ws_eviction
from routers import auth as auth_router
from routers import modules as modules_router
from utils import automation_scheduler
from utils.audit_log import register_audit_log
from utils.body_limit import BodySizeLimitMiddleware
from utils.event_bus import event_bus

logger = logging.getLogger("startup")

# Importing the audit-log module registers its wildcard event-bus subscriber
# (§3.3): from here on, every emitted event is persisted.
register_audit_log()
# Close a user's live WebSockets when they're banned/deleted or leave a team —
# handshake-only authorization can't revoke an already-open socket (#10).
register_ws_eviction(event_bus)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Install-time provisioning that needs the DB (tables come from the migration
    the container runs before this): re-sync the built-in roles to the current
    permission catalog, so an install migrated before a permission was added still
    grants it (§7.3). No admin is seeded — a fresh install is *unconfigured* until
    an operator completes the first-run setup wizard, which creates the owner
    account (ADR-0017, supersedes the seeded default admin of ADR-0010)."""
    async with SessionLocal() as session:
        await seed_system_roles(session)
        # Demo instances seed well-known accounts + sample data (demo-only,
        # idempotent). The hourly reset is external; a fresh boot re-seeds.
        if settings.demo_mode:
            from auth.demo import seed_demo_data

            await seed_demo_data(session)
        # Consistency net (#133): every owner-provisioning path must mark setup
        # complete via `mark_setup_complete`. If an active global Administrator
        # exists but the flag was never set, some path minted an owner without
        # it — the drift that caused GHSA-ccm4 / #132. Warn loudly rather than
        # fix silently: the setup wizard would (correctly) refuse to run, so this
        # points at the real bug instead of masking it.
        from auth.setup import active_global_admin_count, setup_is_complete

        if await active_global_admin_count(session) > 0 and not await setup_is_complete(
            session
        ):
            logger.warning(
                "An active administrator exists but setup was never marked "
                "complete — an owner-provisioning path skipped mark_setup_complete "
                "(#133). The setup wizard is correctly refusing; fix the path."
            )
    # Start the automation time-trigger scheduler (§5.2) — kernel wiring like the
    # audit-log consumer; the tick no-ops until a competition.time_remaining rule
    # exists. Not started under the test transport (no lifespan), so tests drive
    # run_time_rules directly.
    # The time-trigger scheduler is a singleton: under multi-worker it runs as a
    # sidecar process (scheduler.py), not in every web worker, or automations,
    # the update check and retention would fire N× (#189 Phase 3). Single-worker
    # keeps running it here — no sidecar needed.
    if settings.web_concurrency <= 1:
        automation_scheduler.start(
            SessionLocal, settings.automation_scheduler_interval_seconds
        )
    # Cross-worker realtime (#189, ADR-0025/0026): broadcast relay + shared
    # presence. A no-op single-worker; the guard inside refuses to boot a
    # multi-worker deployment with no Redis (broadcasts would otherwise reach
    # only the emitting worker's clients and presence would fragment).
    await start_realtime()
    yield
    await stop_realtime()
    automation_scheduler.stop()


app = FastAPI(title="Flagpost API", version="0.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Compress the larger JSON reads (scoreboard, challenge list, audit log — all
# highly repetitive JSON that deflates ~10x). Small responses skip it so the
# hot small endpoints don't pay the header/CPU overhead.
app.add_middleware(GZipMiddleware, minimum_size=1024)
# Added last = outermost, so an oversized body is refused before CORS/GZip or any
# route reads it (#3). Backstops the per-route upload guards for JSON endpoints.
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)


# Auth, the real-time WebSocket endpoint, and the per-competition module
# toggle are kernel — mounted directly (modules register the room *types* they
# own, §4.1; the loader whose state the toggle manages is itself kernel,
# §11.3). Every feature above the kernel registers through the module loader
# (§11.1): required-core and, since Tier 3, optional modules alike.
app.include_router(auth_router.router)
app.include_router(realtime_router)
app.include_router(modules_router.router)
# Every feature above the kernel — including the audit-log admin surface — mounts
# through the loader (§11.1). The audit-log event-bus *consumer* stays kernel
# (register_audit_log above); the module only adds its query router.
load_modules(app, event_bus, SessionLocal)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/hello")
async def hello() -> dict[str, str]:
    return {"message": "Hello from the Flagpost backend 👋"}
