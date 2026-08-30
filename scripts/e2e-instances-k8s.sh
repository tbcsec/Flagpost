#!/usr/bin/env bash
#
# End-to-end check for the challenge-instance KUBERNETES provisioner (#320,
# ADR-0036 §1). Drives the REAL KubernetesProvisioner against a live single-node
# k3s (booted in Docker, no host installs) — the one thing MockTransport unit
# tests can't: that the composed manifests are accepted by a real API server,
# that RBAC posture is what we claim, that a policy-enforcing CNI actually
# BLOCKS egress, and that a per-instance subdomain routes through Ingress.
#
# It brings k3s up, applies the least-privilege RBAC (k8s/instances-rbac.yaml),
# mints a ServiceAccount token, extracts the API CA, and runs the opt-in pytest
# (backend/tests_e2e) with those in the environment. Wildcard DNS is sslip.io
# (chal.127.0.0.1.sslip.io → 127.0.0.1), so no DNS server or real cert is needed.
#
# Requires: docker (compose v2) + the backend venv (backend/.venv) + outbound
# internet (k3s pulls images; sslip.io resolves). No `nc`, no untrusted input.
#
# Usage:  scripts/e2e-instances-k8s.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="flagpost-k8s-e2e"
COMPOSE=(docker compose -p "$PROJECT" -f "$REPO/docker-compose.instances-k8s.yml")
# The rancher/k3s image ships a `kubectl` symlink (→ k3s's kubectl subcommand,
# via argv[0]); invoke it directly. `k3s kubectl …` resolved to `kubectl kubectl`
# here ("unknown command kubectl for kubectl").
KUBECTL=("${COMPOSE[@]}" exec -T k3s kubectl)

cleanup() { "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "==> Booting single-node k3s"
"${COMPOSE[@]}" up -d

echo "==> Waiting for the API server + a Ready node"
ready=""
last=""
for _ in $(seq 1 120); do   # up to ~6 min: k3s + flannel + traefik on a loaded host
  # Exact STATUS column ("Ready", not "NotReady") — grep-for-Ready would match
  # NotReady, and the API/kubeconfig may not answer for the first few seconds.
  # The `|| true` is load-bearing: under `set -e`, a command substitution in an
  # assignment that fails (kubectl before the API is up, or SIGPIPE from head)
  # aborts the whole script — so swallow the early failures and keep polling.
  last="$("${KUBECTL[@]}" get nodes --no-headers 2>/dev/null | awk '{print $2}' | head -1 || true)"
  [ "$last" = "Ready" ] && { ready="yes"; break; }
  sleep 3
done
if [ -z "$ready" ]; then
  echo "==> FAIL: k3s node never became Ready (last status: ${last:-<none>})"
  "${KUBECTL[@]}" get nodes 2>&1 | head -5 || true
  "${COMPOSE[@]}" logs --tail 40 k3s || true
  exit 1
fi
echo "==> Node Ready"

echo "==> Applying least-privilege RBAC (k8s/instances-rbac.yaml)"
"${KUBECTL[@]}" apply -f - < "$REPO/k8s/instances-rbac.yaml"

echo "==> Minting a ServiceAccount token + reading the API CA"
# `|| true` so a hard kubectl failure yields an empty value the guard can report,
# rather than `set -e` aborting the substitution before the diagnostic (the same
# assignment-command-substitution gotcha as the readiness poll above).
TOKEN="$("${KUBECTL[@]}" -n flagpost-instances create token flagpost-provisioner --duration=1h || true)"
CA="$("${KUBECTL[@]}" config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' 2>/dev/null | base64 -d 2>/dev/null || true)"
[ -n "$TOKEN" ] && [ -n "$CA" ] || { echo "==> FAIL: could not mint token / read CA"; exit 1; }

echo "==> Running the e2e provisioner tests against k3s"
cd "$REPO/backend"
FLAGPOST_E2E_K8S_ENDPOINT="https://127.0.0.1:6443" \
FLAGPOST_E2E_K8S_TOKEN="$TOKEN" \
FLAGPOST_E2E_K8S_CA="$CA" \
FLAGPOST_E2E_K8S_PUBLIC_HOST="127.0.0.1" \
FLAGPOST_E2E_K8S_BASE_DOMAIN="chal.127.0.0.1.sslip.io" \
  .venv/bin/python -m pytest tests_e2e/ -v
echo "==> PASS: the KubernetesProvisioner drove a real k3s cluster end to end."
