#!/usr/bin/env bash
# Hourly demo reset: pull the latest images, wipe all data, and recreate the
# stack. DEMO_MODE re-seeds the accounts + sample data on the fresh boot, so this
# both keeps the demo up to date and resets it every hour.
#
# Driven by deploy/flagpost-demo-reset.timer. Set FLAGPOST_DIR to the directory
# holding docker-compose.demo.yml (default /opt/flagpost).
set -euo pipefail

cd "${FLAGPOST_DIR:-/opt/flagpost}"
COMPOSE=(docker compose -f docker-compose.demo.yml)

"${COMPOSE[@]}" pull
"${COMPOSE[@]}" down -v      # -v wipes the DB/object/secret volumes → clean slate
"${COMPOSE[@]}" up -d
