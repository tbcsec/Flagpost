#!/usr/bin/env bash
# Capture the current state of a Flagpost instance as the "baseline" that
# restore.sh resets to. Run it once after configuring the instance to your
# liking, and again whenever the baseline should change — including after an
# image upgrade. See docs/INTERNAL_DEMO.md.
#
# Only the volume-writing services (backend, minio, postgres) are stopped
# while the volumes are tarred — Postgres is captured in a clean shutdown
# state, and the capture is atomic: the new baseline is written to a staging
# dir and only swapped in (previous baseline → baseline.prev) once complete.
set -euo pipefail
# shellcheck source-path=SCRIPTDIR
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

acquire_lock snapshot
resolve_project
check_volume_coverage
ensure_helper_image

# Refuse to "capture" volumes that don't exist — `docker run -v` would silently
# auto-create empty ones (e.g. under a drifted COMPOSE_PROJECT_NAME), and the
# resulting empty baseline would erase the real data on the next restore.
for vol in "${VOLUMES[@]}"; do
  if ! docker volume inspect "${project}_${vol}" >/dev/null 2>&1; then
    echo "snapshot: volume ${project}_${vol} does not exist — has this stack ever run" >&2
    echo "under project '$project'? (COMPOSE_PROJECT_NAME drift?) Nothing was captured." >&2
    exit 1
  fi
done

STAGING="${BASELINE_DIR}.new"
rm -rf "$STAGING"
mkdir -p "$STAGING"

# Whatever happens past the stop, always try to bring the stack back and never
# leave a half-written staging dir behind. The completed swap clears the trap.
on_fail() {
  echo "snapshot: FAILED — restarting the stack; the previous baseline is untouched" >&2
  "${COMPOSE[@]}" up -d >/dev/null 2>&1 || true
  rm -rf "$STAGING"
}
trap on_fail ERR

"${COMPOSE[@]}" stop "${WRITER_SERVICES[@]}"

for vol in "${VOLUMES[@]}"; do
  docker run --rm \
    -v "${project}_${vol}:/vol:ro" \
    -v "$STAGING:/out" \
    alpine:3 tar czf "/out/${vol}.tgz" -C /vol .
  gzip -t "$STAGING/${vol}.tgz"
done

{
  echo "created: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "project: $project"
  "${COMPOSE[@]}" images
} > "$STAGING/MANIFEST"
"${COMPOSE[@]}" config --images 2>/dev/null | sort > "$STAGING/IMAGES"

# --wait gates on the backend's own compose healthcheck (migrated + serving),
# so a snapshot that leaves the stack broken fails here, visibly, after the
# capture — the staging dir is then discarded and the old baseline stands.
"${COMPOSE[@]}" up -d --wait --wait-timeout 180

# Capture done and the stack is healthy: disarm the recovery trap BEFORE the
# swap, or a failed mv would send on_fail to `rm -rf "$STAGING"` and destroy
# the fresh capture. The swap is same-directory renames, so a failure here
# leaves the new baseline in $STAGING and the old one in place or in .prev.
trap - ERR

# Swap in the new baseline, keeping exactly one previous as a fallback.
rm -rf "${BASELINE_DIR}.prev"
if [ -d "$BASELINE_DIR" ]; then
  mv "$BASELINE_DIR" "${BASELINE_DIR}.prev"
fi
mv "$STAGING" "$BASELINE_DIR"

echo "snapshot: baseline written to $BASELINE_DIR"
