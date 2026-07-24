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
from routers import auth as auth_router
from routers import modules as modules_router
from utils import automation_scheduler
from utils.audit_log import register_audit_log
from utils.event_bus import event_bus

logger = logging.getLogger("startup")

# Importing the audit-log module registers its wildcard event-bus subscriber
# (§3.3): from here on, every emitted event is persisted.
register_audit_log()


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
    # Start the automation time-trigger scheduler (§5.2) — kernel wiring like the
    # audit-log consumer; the tick no-ops until a competition.time_remaining rule
    # exists. Not started under the test transport (no lifespan), so tests drive
    # run_time_rules directly.
    automation_scheduler.start(
        SessionLocal, settings.automation_scheduler_interval_seconds
    )
    yield
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
