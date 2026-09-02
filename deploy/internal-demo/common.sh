# shellcheck shell=bash
# Shared definitions for snapshot.sh / restore.sh — sourced, not executed.
# Everything both scripts must agree on lives here so they cannot drift.

# Default to the checkout this file lives in; FLAGPOST_DIR overrides.
FLAGPOST_DIR="${FLAGPOST_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$FLAGPOST_DIR" || exit 1

# Plain `docker compose` (no -f): honours docker-compose.override.yml and .env
# exactly like the operator's own `docker compose up -d` — an explicit -f would
# silently strip their overrides on every stop/up cycle.
COMPOSE=(docker compose)

BASELINE_DIR="${BASELINE_DIR:-$FLAGPOST_DIR/deploy/internal-demo/baseline}"
# A relative dir would later be parsed by `docker run -v` as a *named volume*,
# not a path — refuse early instead.
case "$BASELINE_DIR" in
  /*) ;;
  *) echo "internal-demo: BASELINE_DIR must be an absolute path (got '$BASELINE_DIR')" >&2; exit 1 ;;
esac

# The volumes that ARE the instance state, and the ones that deliberately
# aren't (Caddy's cert/config cache renews on its own schedule).
VOLUMES=(postgres-data minio-data backend-data)
EXCLUDED_VOLUMES=(caddy-data caddy-config)

# The services that write those volumes. Only these are stopped during a
# snapshot/restore — caddy keeps answering (with errors) instead of the port
# going dead, and unchanged containers are reused so `down`-churn doesn't leak
# the redis image's anonymous /data volume every cycle.
# shellcheck disable=SC2034  # consumed by the sourcing scripts
WRITER_SERVICES=(backend minio postgres)

# Resolve the compose project name (honours COMPOSE_PROJECT_NAME and the
# file's `name:`) so both scripts always target the same `<project>_<volume>`
# Docker volumes. Deliberately not 2>/dev/null and guarded with `|| true`:
# under `set -euo pipefail` a failing substitution would otherwise kill the
# script before the diagnostic below ever printed.
resolve_project() {
  project="$("${COMPOSE[@]}" config 2>&1 | sed -n 's/^name: //p' | head -n1 || true)"
  if [ -z "${project:-}" ]; then
    echo "internal-demo: could not resolve the compose project name — is docker running," >&2
    echo "and does 'docker compose config' succeed in $FLAGPOST_DIR? (needs compose v2.6+)" >&2
    exit 1
  fi
}

# Fail if the compose file (or an override) declares a volume this tooling
# doesn't know about — a new stateful volume must be added to VOLUMES (or
# EXCLUDED_VOLUMES) here, or every "reset" would silently skip it.
check_volume_coverage() {
  local declared known v
  declared="$("${COMPOSE[@]}" config --volumes 2>/dev/null || true)"
  known=" ${VOLUMES[*]} ${EXCLUDED_VOLUMES[*]} "
  for v in $declared; do
    if [ "${known#* "$v" }" = "$known" ]; then
      echo "internal-demo: compose declares volume '$v', which is neither snapshotted nor" >&2
      echo "excluded — add it to VOLUMES or EXCLUDED_VOLUMES in deploy/internal-demo/common.sh" >&2
      exit 1
    fi
  done
}

# One operation at a time: a manual snapshot racing the reset timer would
# capture a torn baseline. Callers pass a label for the refusal message.
# NB: fd 9 is inherited by child processes, so every docker command in these
# scripts must stay foreground — a backgrounded/detached one would inherit the
# fd and hold the lock past script exit, wedging every future reset.
acquire_lock() {
  exec 9>"$FLAGPOST_DIR/deploy/internal-demo/.lock"
  if ! flock -n 9; then
    echo "internal-demo: another snapshot/restore is already running — $1 aborted" >&2
    exit 1
  fi
}

# The tar helper image, fetched while the stack is still up — a pull failure
# mid-reset (pruned image, offline host) must not strand the stack stopped.
ensure_helper_image() {
  docker image inspect alpine:3 >/dev/null 2>&1 || docker pull -q alpine:3 >/dev/null
}
