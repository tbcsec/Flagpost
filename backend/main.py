"""FastAPI entrypoint.

Tier 0 skeleton: a health check and a hello-world endpoint the frontend
fetches to prove the two sides talk. No domain routers, models, event bus,
or auth yet — those are Tier 0 features (see docs/ROADMAP.md), and each new
domain gets its own router under `routers/` per ARCHITECTURE.md §14.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
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


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/hello")
async def hello() -> dict[str, str]:
    return {"message": "Hello from the CTF Platform backend 👋"}
