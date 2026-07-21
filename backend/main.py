"""FastAPI entrypoint.

Wires the audit-log event subscriber and mounts one router per domain
(ARCHITECTURE.md §14). The hello/health endpoints from the Tier 0 skeleton
remain as a liveness/connectivity check.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth.seed import (
    DEFAULT_ADMIN_EMAIL,
    admin_has_default_password,
    seed_admin_user,
)
from config import settings
from db import SessionLocal
from plugins.loader import load_modules
from realtime import router as realtime_router
from routers import auth as auth_router
from utils.audit_log import register_audit_log
from utils.event_bus import event_bus

logger = logging.getLogger("startup")

# Importing the audit-log module registers its wildcard event-bus subscriber
# (§3.3): from here on, every emitted event is persisted.
register_audit_log()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Install-time provisioning that needs the DB (tables come from the
    migration the container runs before this): seed the default administrator
    and warn loudly while it still has its default password (ADR-0010)."""
    async with SessionLocal() as session:
        await seed_admin_user(session)
        if await admin_has_default_password(session):
            logger.warning(
                "SECURITY: administrator '%s' is still using the DEFAULT "
                "password. Change it now via POST /api/auth/change-password.",
                DEFAULT_ADMIN_EMAIL,
            )
    yield


app = FastAPI(title="Flagpost API", version="0.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Auth and the real-time WebSocket endpoint are kernel — mounted directly
# (modules register the room *types* they own, §4.1). Every feature above the
# kernel registers through the module loader (§11.1): required-core now,
# optional modules later.
app.include_router(auth_router.router)
app.include_router(realtime_router)
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
