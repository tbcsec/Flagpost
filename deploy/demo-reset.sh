#!/usr/bin/env bash
# Hourly demo reset: refresh the checkout, pull the latest images, wipe all data,
# and recreate the stack. DEMO_MODE re-seeds the accounts + sample data on the
# fresh boot, so this both keeps the demo up to date and resets it every hour.
#
# Driven by deploy/flagpost-demo-reset.timer. Set FLAGPOST_DIR to the directory
# holding docker-compose.demo.yml (default /opt/flagpost).
#
# Design rule: the WIPE is the job. Everything before it (git pull, image pull)
# is a best-effort refresh and must never be able to stop the reset — otherwise a
# transient hiccup leaves the demo running with accumulated data indefinitely.
set -euo pipefail

log() { echo "demo-reset: $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

cd "${FLAGPOST_DIR:-/opt/flagpost}"
COMPOSE=(docker compose -f docker-compose.demo.yml)

log "starting reset"

# Pull repo changes first so compose/config edits on main propagate on their own
# (a new service, changed env, etc. — image *code* already rides the image pull
# below). Non-fatal: a pull failure (local edits, offline) must not stop the
# reset, so the demo stays up on the last-known-good checkout. .env (the tunnel
# token) is gitignored, so it's never touched.
git pull --ff-only || log "git pull failed — continuing on the current checkout"

# Pulling the latest images keeps the demo current, but it must NOT be able to
# block the reset. The stack pulls several Docker Hub images (postgres, redis,
# minio, caddy, cloudflared), and Docker Hub's anonymous pull rate limit means a
# single 429 — or any transient registry error — makes `compose pull` exit
# non-zero. Under `set -e` that would abort the script *before* the wipe below,
# so the demo would keep running on its cached images with data piling up and
# never reset (observed: ~100k accumulated accounts). Make it best-effort: on
# failure we recreate from the images already on disk and pick up newer ones on
# a later run that pulls cleanly.
"${COMPOSE[@]}" pull || log "image pull failed — recreating from cached images"

# The reset itself. This always runs. `-v` wipes the DB/object/secret volumes →
# clean slate; `--remove-orphans` drops containers for any service removed from
# the compose file so a stale one can't linger across resets.
log "wiping volumes and recreating the stack"
"${COMPOSE[@]}" down -v --remove-orphans
"${COMPOSE[@]}" up -d

# Reclaim space from images the hourly pulls leave dangling. Hourly image churn
# over weeks can otherwise fill the disk, which degrades the box (a likely
# contributor to "the demo is getting slow"). Dangling-only + best-effort, so it
# never removes an in-use image and never fails the reset.
docker image prune -f >/dev/null 2>&1 || log "image prune skipped"

log "reset complete"
