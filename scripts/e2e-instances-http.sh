#!/usr/bin/env bash
#
# End-to-end check for the challenge-instance HTTP ingress (#319, ADR-0036 §4).
#
# Proves the one thing unit tests can't: that a container carrying the caddy
# routing labels the Docker provisioner emits is actually reached at
# `https://<token>.<base_domain>` through the caddy-docker-proxy ingress, with
# TLS terminated. The provisioner → labels mapping itself is unit-tested
# (backend/tests/test_provisioner_docker.py::test_create_http_exposure...).
#
# It stands up the ingress from docker-compose.instances-http.yml, launches a
# throwaway `traefik/whoami` on the instance network with the SAME labels the
# provisioner sets, and curls the per-instance subdomain over HTTPS.
#
# Wildcard DNS is provided by sslip.io: <anything>.chal.127.0.0.1.sslip.io
# resolves to 127.0.0.1 with no DNS server to run. TLS is Caddy's internal CA.
#
# Requires: docker (compose v2) + outbound DNS (for sslip.io). Uses only the
# known-good traefik/whoami image; no untrusted input is ever executed.
#
# Usage:  scripts/e2e-instances-http.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# A dedicated project name isolates the harness from any dev/prod stack sharing
# this directory — so `down -v` and orphan handling can never touch it.
COMPOSE=(docker compose -p flagpost-instances-e2e -f "$REPO/docker-compose.instances-http.yml")
BASE_DOMAIN="chal.127.0.0.1.sslip.io"
# A subdomain token in the provisioner's shape (8-char Crockford base32).
TOKEN="e2e${RANDOM}z"
FQDN="${TOKEN}.${BASE_DOMAIN}"
WHOAMI="flagpost-e2e-whoami"

cleanup() {
  docker rm -f "$WHOAMI" >/dev/null 2>&1 || true
  "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Bringing up the caddy-docker-proxy ingress"
"${COMPOSE[@]}" up -d caddy-socket-proxy caddy-ingress

echo "==> Launching a whoami instance with the provisioner's caddy labels"
# EXACTLY the labels DockerProvisioner._container_body emits for exposure=http.
docker run -d --name "$WHOAMI" \
  --network flagpost-instances \
  --label "io.flagpost.managed=true" \
  --label "caddy=${FQDN}" \
  --label 'caddy.reverse_proxy={{upstreams 80}}' \
  traefik/whoami >/dev/null

echo "==> Probing https://${FQDN}/ (waiting for caddy to route + issue its cert)"
ok=""
for i in $(seq 1 30); do
  code="$(curl -sk -o /tmp/e2e_body.$$ -w '%{http_code}' --max-time 5 "https://${FQDN}/" || true)"
  if [ "$code" = "200" ] && grep -q "Hostname:" /tmp/e2e_body.$$ 2>/dev/null; then
    ok="yes"; break
  fi
  sleep 2
done
rm -f /tmp/e2e_body.$$

if [ -n "$ok" ]; then
  echo "==> PASS: the instance is reachable at https://${FQDN}/ over TLS, routed to whoami."
  exit 0
fi
echo "==> FAIL: https://${FQDN}/ did not return a whoami 200 within the timeout."
echo "    Last HTTP code: ${code:-none}. Ingress logs:"
"${COMPOSE[@]}" logs --tail 40 caddy-ingress || true
exit 1
