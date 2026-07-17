"""FastAPI entrypoint.

Wires the audit-log event subscriber and mounts one router per domain
(ARCHITECTURE.md §14). The hello/health endpoints from the Tier 0 skeleton
remain as a liveness/connectivity check.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routers import auth as auth_router
from routers import competitions as competitions_router
from utils.audit_log import register_audit_log

# Importing the audit-log module registers its wildcard event-bus subscriber
# (§3.3): from here on, every emitted event is persisted.
register_audit_log()

app = FastAPI(title="CTF Platform API", version="0.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth_router.router)
app.include_router(competitions_router.router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/hello")
async def hello() -> dict[str, str]:
    return {"message": "Hello from the CTF Platform backend 👋"}
