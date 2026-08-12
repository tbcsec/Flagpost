#!/bin/sh
# Production backend entrypoint (#189 Phase 3).
#
# 1. Migrate once (creates tables + seeds the built-in roles) before any worker
#    serves — so the per-worker lifespan re-sync only ever UPDATEs, never races
#    on the fresh-DB insert.
# 2. Resolve the worker count. WEB_CONCURRENCY wins if set; otherwise 1 for now
#    (Phase 4 flips this default to the core-aware value). Export it so the app's
#    settings.web_concurrency matches --workers (it drives the relay/presence/
#    pool decisions).
# 3. Multi-worker only: start the singleton scheduler as a sidecar process, so
#    automations/update-check/retention don't fire once per web worker.
# 4. Exec uvicorn with the resolved worker count.
set -e

alembic upgrade head

WORKERS="${WEB_CONCURRENCY:-1}"
export WEB_CONCURRENCY="$WORKERS"

if [ "$WORKERS" -gt 1 ]; then
    echo "entrypoint: multi-worker ($WORKERS) — starting scheduler sidecar"
    python -m scheduler &
fi

exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers "$WORKERS"
