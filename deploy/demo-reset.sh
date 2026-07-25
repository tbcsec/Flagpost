#!/usr/bin/env bash
# Hourly demo reset: refresh the checkout, pull the latest images, wipe all data,
# and recreate the stack. DEMO_MODE re-seeds the accounts + sample data on the
# fresh boot, so this both keeps the demo up to date and resets it every hour.
#
# Driven by deploy/flagpost-demo-reset.timer. Set FLAGPOST_DIR to the directory
# holding docker-compose.demo.yml (default /opt/flagpost).
set -euo pipefail

cd "${FLAGPOST_DIR:-/opt/flagpost}"
COMPOSE=(docker compose -f docker-compose.demo.yml)

# Pull repo changes first so compose/config edits on main propagate on their own
# (a new service, changed env, etc. — image *code* already rides the image pull
# below). Non-fatal: a pull failure (local edits, offline) must not stop the
# reset, so the demo stays up on the last-known-good checkout. .env (the tunnel
# token) is gitignored, so it's never touched.
git pull --ff-only || echo "demo-reset: git pull failed — continuing on the current checkout"

"${COMPOSE[@]}" pull
"${COMPOSE[@]}" down -v      # -v wipes the DB/object/secret volumes → clean slate
"${COMPOSE[@]}" up -d
