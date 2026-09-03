#!/usr/bin/env bash
#
# End-to-end check for the internal-demo baseline snapshot/restore (#356).
#
# Proves the full operator loop against a real production stack: first-run
# setup → author a baseline (branding + a competition) → snapshot.sh → drift
# the state (rename the site, add a competition, register a user) →
# restore.sh → assert the instance is byte-identically back at the baseline.
# Then the safety rails: restore must refuse a missing, corrupt, or
# wrong-project baseline without touching anything, and the deploy scripts'
# stop/up cycle must preserve a docker-compose.override.yml customisation.
#
# Isolation: a hard-coded compose project name (ambient COMPOSE_PROJECT_NAME
# is ignored — the first stack step is `down -v`, which must never resolve to
# a real deployment), a throwaway mktemp baseline dir (ambient BASELINE_DIR
# likewise ignored), and COMPOSE_ENV_FILES=/dev/null so a checkout's .env
# can't skew ports or DEMO_MODE. Host ports are still the production stack's
# real 8080/443/127.0.0.1:9000 — stop anything holding those first
# (e.g. `docker compose -f docker-compose.dev.yml stop`).
#
# Requires: docker (compose v2.24+), curl, python3. Tears everything down on
# exit unless it failed (kept for inspection) or KEEP=1.
#
# Usage:  scripts/e2e-internal-demo.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
export COMPOSE_PROJECT_NAME=flagpost-e2e-demo
export COMPOSE_ENV_FILES=/dev/null
export FLAGPOST_DIR="$REPO"
SCRATCH="$(mktemp -d /tmp/flagpost-e2e-baseline.XXXXXX)"
export BASELINE_DIR="$SCRATCH/baseline"
COMPOSE=(docker compose)
BASE="http://localhost:8080/api"
CREATED_OVERRIDE=0
fail=0
done=0

say() { echo; echo "==> $*"; }
on_exit() {
  local rc=$?
  [ "$CREATED_OVERRIDE" = 1 ] && rm -f "$REPO/docker-compose.override.yml"
  if [ "$rc" = 0 ] && [ "$done" = 1 ] && [ "${KEEP:-0}" != 1 ]; then
    say "cleanup"
    "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true
    rm -rf "$SCRATCH"
  else
    echo "==> stack '$COMPOSE_PROJECT_NAME' and $SCRATCH kept for inspection" >&2
    echo "==> tear down with: COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME docker compose down -v" >&2
  fi
}
trap on_exit EXIT

wait_health() {
  local deadline=$(( $(date +%s) + 240 ))
  until curl -fsS "$BASE/health" >/dev/null 2>&1; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      echo "FATAL: app not healthy within 240s"
      "${COMPOSE[@]}" logs --tail 30 backend || true
      exit 1
    fi
    sleep 3
  done
}
json_field() {  # json_field <field> — reads JSON on stdin
  python3 -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"
}
login_token() {  # login_token <identifier> <password> — empty on failure
  curl -fsS -X POST "$BASE/auth/login" -H 'content-type: application/json' \
    -d "{\"identifier\": \"$1\", \"password\": \"$2\"}" | json_field access_token || true
}
login_code() {  # login_code <identifier> <password> — HTTP status
  curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/auth/login" \
    -H 'content-type: application/json' \
    -d "{\"identifier\": \"$1\", \"password\": \"$2\"}" || echo 000
}
comp_names() {
  curl -fsS "$BASE/competitions" -H "authorization: Bearer $1" |
    python3 -c 'import json,sys; print(sorted(c["name"] for c in json.load(sys.stdin)))' || echo ERROR
}
platform_name() {
  curl -fsS "$BASE/site-settings" | json_field platform_name || echo ERROR
}
check() {  # check <label> <actual> <expected>
  if [ "$2" = "$3" ]; then echo "PASS: $1"; else echo "FAIL: $1 → '$2' (wanted '$3')"; fail=1; fi
}

say "build + fresh stack ($COMPOSE_PROJECT_NAME)"
"${COMPOSE[@]}" down -v >/dev/null 2>&1 || true
"${COMPOSE[@]}" up -d --build
wait_health

say "first-run setup (owner) + author the baseline"
TOKEN=$(curl -fsS -X POST "$BASE/setup" -H 'content-type: application/json' -d '{
  "admin": {"display_name": "owner", "password": "ownerpass123"},
  "platform_name": "Baseline Corp CTF", "default_palette": "midnight",
  "accent": "#7c3aed", "registration_open": true, "update_checks_enabled": false
}' | json_field access_token)
curl -fsS -X POST "$BASE/competitions" -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"name": "Corp Internal CTF 2026", "participation_mode": "individual", "visibility": "public"}' >/dev/null
echo "    baseline: platform='$(platform_name)' competitions=$(comp_names "$TOKEN")"

say "snapshot.sh"
deploy/internal-demo/snapshot.sh
wait_health

say "drift the state past the baseline"
curl -fsS -X PUT "$BASE/site-settings" -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"platform_name": "DRIFTED NAME", "default_palette": "midnight", "accent": "#7c3aed"}' >/dev/null
curl -fsS -X POST "$BASE/competitions" -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"name": "Drift Comp", "participation_mode": "individual"}' >/dev/null
curl -fsS -X POST "$BASE/auth/register" -H 'content-type: application/json' \
  -d '{"display_name": "drift_user", "password": "driftpass123"}' >/dev/null
# Minted just before the restore: proves an unexpired access token (stateless,
# signed with the baseline's JWT secret) still validates afterwards.
PRE_RESTORE_TOKEN="$(login_token owner ownerpass123)"
echo "    drifted:  platform='$(platform_name)'"

say "restore.sh"
deploy/internal-demo/restore.sh

say "assertions"
me=$(curl -fsS "$BASE/auth/me" -H "authorization: Bearer $PRE_RESTORE_TOKEN" |
  json_field display_name || echo TOKEN-REJECTED)
check "pre-restore access token still valid" "$me" "owner"
check "platform_name restored" "$(platform_name)" "Baseline Corp CTF"
check "owner re-login" "$(login_code owner ownerpass123)" "200"
FRESH_TOKEN="$(login_token owner ownerpass123)"
check "competitions = baseline" "$(comp_names "$FRESH_TOKEN")" "['Corp Internal CTF 2026']"
drift_code="$(login_code drift_user driftpass123)"
case "$drift_code" in
  4*) echo "PASS: drift_user erased ($drift_code)" ;;
  *) echo "FAIL: drift_user login → $drift_code"; fail=1 ;;
esac

say "restore refuses a missing baseline"
refusal=$(BASELINE_DIR=/nonexistent deploy/internal-demo/restore.sh 2>&1 || true)
if echo "$refusal" | grep -q "nothing was touched" && curl -fsS "$BASE/health" >/dev/null; then
  echo "PASS: refused cleanly, stack untouched"
else
  echo "FAIL: missing-baseline refusal → $refusal"; fail=1
fi

say "restore refuses a corrupt baseline"
cp -r "$BASELINE_DIR" "$SCRATCH/corrupt"
head -c 100 "$SCRATCH/corrupt/minio-data.tgz" > "$SCRATCH/corrupt/minio-data.tgz.t" \
  && mv "$SCRATCH/corrupt/minio-data.tgz.t" "$SCRATCH/corrupt/minio-data.tgz"
refusal=$(BASELINE_DIR="$SCRATCH/corrupt" deploy/internal-demo/restore.sh 2>&1 || true)
if echo "$refusal" | grep -q "corrupt" && curl -fsS "$BASE/health" >/dev/null; then
  echo "PASS: corrupt tarball refused before any wipe"
else
  echo "FAIL: corrupt-baseline refusal → $refusal"; fail=1
fi

say "restore refuses a baseline from another compose project"
cp -r "$BASELINE_DIR" "$SCRATCH/wrongproj"
sed -i 's/^project: .*/project: some-other-stack/' "$SCRATCH/wrongproj/MANIFEST"
refusal=$(BASELINE_DIR="$SCRATCH/wrongproj" deploy/internal-demo/restore.sh 2>&1 || true)
if echo "$refusal" | grep -q "drift" && curl -fsS "$BASE/health" >/dev/null; then
  echo "PASS: wrong-project baseline refused"
else
  echo "FAIL: project-mismatch refusal → $refusal"; fail=1
fi

say "operator override survives the scripts' stop/up cycle"
if [ -e "$REPO/docker-compose.override.yml" ]; then
  echo "SKIP: a real docker-compose.override.yml exists in this checkout"
else
  CREATED_OVERRIDE=1
  printf 'services:\n  backend:\n    environment:\n      FLAGPOST_E2E_MARKER: "1"\n' \
    > "$REPO/docker-compose.override.yml"
  deploy/internal-demo/snapshot.sh   # recreates backend with the override merged
  wait_health
  marker=$("${COMPOSE[@]}" exec -T backend printenv FLAGPOST_E2E_MARKER || echo MISSING)
  check "override env present after script-driven up" "$marker" "1"
  rm -f "$REPO/docker-compose.override.yml"; CREATED_OVERRIDE=0
fi

done=1
if [ "$fail" != 0 ]; then
  echo "==> FAIL: see assertions above"
  exit 1
fi
echo "==> PASS: snapshot → drift → restore round-trip + safety rails verified"
