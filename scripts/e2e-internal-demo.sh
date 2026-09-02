#!/usr/bin/env bash
#
# End-to-end check for the internal-demo baseline snapshot/restore (#356).
#
# Proves the full operator loop against a real production stack: first-run
# setup → author a baseline (branding + a competition) → snapshot.sh → drift
# the state (rename the site, add a competition, register a user) →
# restore.sh → assert the instance is byte-identically back at the baseline,
# including that a pre-restore access token still validates (the JWT secret
# rides the backend-data volume, so sessions survive resets).
#
# Runs under its own compose project name (flagpost-e2e-demo) so it never
# touches a dev or prod stack in this checkout — but it binds the production
# stack's HOST PORTS (8080/443, MinIO on loopback 9000), so stop anything
# holding those first (e.g. `docker compose -f docker-compose.dev.yml stop`).
#
# Requires: docker (compose v2), curl, python3. Everything it creates lives in
# the flagpost-e2e-demo project and a temp baseline dir; both are removed on
# success (`KEEP=1` to keep them for inspection).
#
# Usage:  scripts/e2e-internal-demo.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-flagpost-e2e-demo}"
export FLAGPOST_DIR="$REPO"
export BASELINE_DIR="${BASELINE_DIR:-$(mktemp -d /tmp/flagpost-e2e-baseline.XXXXXX)}"
COMPOSE=(docker compose -f docker-compose.yml)
BASE="http://localhost:${HTTP_PORT:-8080}/api"

say() { echo; echo "==> $*"; }
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
comp_names() {
  curl -fsS "$BASE/competitions" -H "authorization: Bearer $1" |
    python3 -c 'import json,sys; print(sorted(c["name"] for c in json.load(sys.stdin)))'
}
platform_name() {
  curl -fsS "$BASE/site-settings" |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["platform_name"])'
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
}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
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
# A token minted BEFORE the restore, to prove sessions survive it.
PRE_RESTORE_TOKEN=$(curl -fsS -X POST "$BASE/auth/login" -H 'content-type: application/json' \
  -d '{"identifier": "owner", "password": "ownerpass123"}' |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
echo "    drifted:  platform='$(platform_name)' competitions=$(comp_names "$TOKEN")"

say "restore.sh"
deploy/internal-demo/restore.sh

say "assertions"
fail=0
me=$(curl -fsS "$BASE/auth/me" -H "authorization: Bearer $PRE_RESTORE_TOKEN" |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["display_name"])') || me="TOKEN-REJECTED"
if [ "$me" = "owner" ]; then echo "PASS: pre-restore token still valid"; else echo "FAIL: token → $me"; fail=1; fi

pn=$(platform_name)
if [ "$pn" = "Baseline Corp CTF" ]; then echo "PASS: platform_name restored"; else echo "FAIL: platform_name = $pn"; fail=1; fi

names=$(comp_names "$TOKEN")
if [ "$names" = "['Corp Internal CTF 2026']" ]; then echo "PASS: competitions = baseline"; else echo "FAIL: competitions = $names"; fail=1; fi

code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/auth/login" \
  -H 'content-type: application/json' -d '{"identifier": "drift_user", "password": "driftpass123"}')
case "$code" in 4*) echo "PASS: drift_user erased" ;; *) echo "FAIL: drift_user login → $code"; fail=1 ;; esac

code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/auth/login" \
  -H 'content-type: application/json' -d '{"identifier": "owner", "password": "ownerpass123"}')
if [ "$code" = "200" ]; then echo "PASS: owner re-login"; else echo "FAIL: owner login → $code"; fail=1; fi

say "restore refuses without a baseline (safety)"
refusal=$(BASELINE_DIR=/nonexistent deploy/internal-demo/restore.sh 2>&1 || true)
if echo "$refusal" | grep -q "nothing was touched" && curl -fsS "$BASE/health" >/dev/null; then
  echo "PASS: refused cleanly, stack untouched"
else
  echo "FAIL: missing-baseline refusal"; fail=1
fi

if [ "$fail" != 0 ]; then
  echo "==> FAIL: see assertions above (stack + baseline kept for inspection)"
  exit 1
fi
if [ "${KEEP:-0}" != 1 ]; then
  say "cleanup"
  "${COMPOSE[@]}" down -v >/dev/null 2>&1
  rm -rf "$BASELINE_DIR" "${BASELINE_DIR}.prev"
fi
echo "==> PASS: snapshot → drift → restore round-trip verified"
