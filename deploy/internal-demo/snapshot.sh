#!/usr/bin/env bash
# Capture the current state of a Flagpost instance as the "baseline" that
# restore.sh resets to. Run it once after configuring the instance to your
# liking (branding, competitions, users, ...), and again whenever the baseline
# should change — including after an image upgrade. See docs/INTERNAL_DEMO.md.
#
# Stops the stack first so the Postgres data directory is captured in a clean
# shutdown state, tars the three data volumes, then starts the stack again.
# Caddy's cert/config cache is deliberately not part of the baseline.
set -euo pipefail

FLAGPOST_DIR="${FLAGPOST_DIR:-/opt/flagpost}"
cd "$FLAGPOST_DIR"
COMPOSE=(docker compose -f docker-compose.yml)
BASELINE_DIR="${BASELINE_DIR:-$FLAGPOST_DIR/deploy/internal-demo/baseline}"
VOLUMES=(postgres-data minio-data backend-data)

# Resolve the compose project name (honours the file's `name:` and any
# COMPOSE_PROJECT_NAME override) so snapshot and restore always target the
# same `<project>_<volume>` Docker volumes.
project="$("${COMPOSE[@]}" config 2>/dev/null | sed -n 's/^name: //p' | head -n1)"
if [ -z "$project" ]; then
  echo "snapshot: could not resolve the compose project name" >&2
  exit 1
fi

# Keep exactly one previous baseline around as a fallback.
if [ -d "$BASELINE_DIR" ] && compgen -G "$BASELINE_DIR/*.tgz" >/dev/null; then
  rm -rf "${BASELINE_DIR}.prev"
  mv "$BASELINE_DIR" "${BASELINE_DIR}.prev"
fi
mkdir -p "$BASELINE_DIR"

"${COMPOSE[@]}" stop

for vol in "${VOLUMES[@]}"; do
  docker run --rm \
    -v "${project}_${vol}:/vol:ro" \
    -v "$BASELINE_DIR:/out" \
    alpine:3 tar czf "/out/${vol}.tgz" -C /vol .
done

{
  echo "created: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "project: $project"
  "${COMPOSE[@]}" images
} > "$BASELINE_DIR/MANIFEST"

"${COMPOSE[@]}" up -d
echo "snapshot: baseline written to $BASELINE_DIR"
