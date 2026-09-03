#!/usr/bin/env bash
# Reset a Flagpost instance to the baseline captured by snapshot.sh: stop the
# volume-writing services, restore the data volumes from the baseline
# tarballs, start the stack. Driven by flagpost-internal-demo-reset.timer, or
# run by hand. See docs/INTERNAL_DEMO.md.
#
# Every destructive step is preceded by preflight checks (complete AND intact
# baseline, matching compose project) so a bad baseline is refused before any
# volume is touched. Unlike the public demo's reset (deploy/demo-reset.sh)
# this neither pulls the repo nor the app images: an internal demo pins a
# stable baseline, and an upgrade is an explicit "pull, verify, re-snapshot".
set -euo pipefail
# shellcheck source-path=SCRIPTDIR
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

acquire_lock restore
resolve_project
check_volume_coverage

# --- Preflight: refuse, touching nothing, unless the baseline is usable. ---
for vol in "${VOLUMES[@]}"; do
  if [ ! -f "$BASELINE_DIR/$vol.tgz" ]; then
    echo "restore: $BASELINE_DIR/$vol.tgz missing — run snapshot.sh first; nothing was touched" >&2
    exit 1
  fi
  if ! gzip -t "$BASELINE_DIR/$vol.tgz" 2>/dev/null; then
    echo "restore: $BASELINE_DIR/$vol.tgz is corrupt — re-run snapshot.sh (or recover" >&2
    echo "restore: ${BASELINE_DIR}.prev); nothing was touched" >&2
    exit 1
  fi
done

# A baseline captured under a different compose project would wipe the wrong
# stack's volumes — refuse instead (the MANIFEST records the capturing project).
if [ -f "$BASELINE_DIR/MANIFEST" ]; then
  baseline_project="$(sed -n 's/^project: //p' "$BASELINE_DIR/MANIFEST" | head -n1 || true)"
  if [ -n "$baseline_project" ] && [ "$baseline_project" != "$project" ]; then
    echo "restore: baseline was captured under project '$baseline_project' but this run" >&2
    echo "restore: resolves '$project' (COMPOSE_PROJECT_NAME drift?); nothing was touched" >&2
    exit 1
  fi
fi

# Image drift is legal (migrations re-run on boot) but worth a loud note —
# a rolled-back image serving a newer baseline schema breaks silently.
if [ -f "$BASELINE_DIR/IMAGES" ]; then
  current_images="$("${COMPOSE[@]}" config --images 2>/dev/null | sort || true)"
  if [ -n "$current_images" ] && [ "$current_images" != "$(cat "$BASELINE_DIR/IMAGES")" ]; then
    echo "restore: WARNING — stack images differ from the baseline's (see $BASELINE_DIR/MANIFEST);" >&2
    echo "restore: if you upgraded, re-run snapshot.sh; if you rolled back, expect breakage" >&2
  fi
fi

ensure_helper_image

# On a host that never ran the stack, create the compose-labelled volumes (and
# containers) before restoring into them.
for vol in "${VOLUMES[@]}"; do
  if ! docker volume inspect "${project}_${vol}" >/dev/null 2>&1; then
    "${COMPOSE[@]}" up --no-start
    break
  fi
done

# Past this point the volumes get wiped — on any failure, still try to bring
# the stack up so the host isn't left dark, and say what happened.
on_fail() {
  echo "restore: FAILED mid-restore — attempting to start the stack anyway;" >&2
  echo "restore: check 'docker compose logs backend' and consider ${BASELINE_DIR}.prev" >&2
  "${COMPOSE[@]}" up -d >/dev/null 2>&1 || true
}
trap on_fail ERR

"${COMPOSE[@]}" stop "${WRITER_SERVICES[@]}"

for vol in "${VOLUMES[@]}"; do
  # set -e + `;` (not `&&`): a wipe that fails part-way aborts before the
  # extract and trips the ERR trap, rather than silently skipping the restore
  # and leaving an empty volume the stack would then boot on.
  docker run --rm \
    -v "${project}_${vol}:/vol" \
    -v "$BASELINE_DIR:/in:ro" \
    alpine:3 sh -c "set -e; find /vol -mindepth 1 -delete; tar xzf /in/${vol}.tgz -C /vol"
done

# --wait gates on the backend's compose healthcheck (in-container /api/health),
# which works identically behind TLS/tunnel topologies where an external curl
# would only ever see Caddy's redirect. Failure fails the systemd unit visibly.
"${COMPOSE[@]}" up -d --wait --wait-timeout 180
trap - ERR

addr="$("${COMPOSE[@]}" port caddy 80 2>/dev/null | head -n1 || true)"
echo "restore: baseline restored, app healthy${addr:+ at http://$addr}"
