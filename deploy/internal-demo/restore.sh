#!/usr/bin/env bash
# Reset a Flagpost instance to the baseline captured by snapshot.sh: stop the
# stack, restore the three data volumes from the baseline tarballs, start the
# stack. Driven by flagpost-internal-demo-reset.timer, or run by hand.
# See docs/INTERNAL_DEMO.md.
#
# Unlike the public demo's reset (deploy/demo-reset.sh) this neither pulls the
# repo nor the images: an internal demo pins a stable baseline, and an upgrade
# is an explicit "pull, verify, re-snapshot" (see the guide).
set -euo pipefail

FLAGPOST_DIR="${FLAGPOST_DIR:-/opt/flagpost}"
cd "$FLAGPOST_DIR"
COMPOSE=(docker compose -f docker-compose.yml)
BASELINE_DIR="${BASELINE_DIR:-$FLAGPOST_DIR/deploy/internal-demo/baseline}"
VOLUMES=(postgres-data minio-data backend-data)

# Never wipe anything unless the complete baseline is present.
for vol in "${VOLUMES[@]}"; do
  if [ ! -f "$BASELINE_DIR/$vol.tgz" ]; then
    echo "restore: $BASELINE_DIR/$vol.tgz missing — run snapshot.sh first; nothing was touched" >&2
    exit 1
  fi
done

project="$("${COMPOSE[@]}" config 2>/dev/null | sed -n 's/^name: //p' | head -n1)"
if [ -z "$project" ]; then
  echo "restore: could not resolve the compose project name" >&2
  exit 1
fi

"${COMPOSE[@]}" down             # containers go; volumes stay (no -v)
"${COMPOSE[@]}" up --no-start    # (re)creates compose-labelled volumes on any host

for vol in "${VOLUMES[@]}"; do
  docker run --rm \
    -v "${project}_${vol}:/vol" \
    -v "$BASELINE_DIR:/in:ro" \
    alpine:3 sh -c "find /vol -mindepth 1 -delete && tar xzf /in/${vol}.tgz -C /vol"
done

"${COMPOSE[@]}" up -d

# Bounded wait for the app to come back: a restore that boots into a broken
# stack should fail the systemd unit visibly, not exit green.
addr="$("${COMPOSE[@]}" port caddy 80 2>/dev/null | head -n1)"
addr="${addr:-localhost:8080}"
deadline=$(( $(date +%s) + 180 ))
until curl -fsS "http://${addr}/api/health" >/dev/null 2>&1; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "restore: app not healthy after 180s — check 'docker compose logs backend'" >&2
    exit 1
  fi
  sleep 3
done
echo "restore: baseline restored, app healthy at http://${addr}"
