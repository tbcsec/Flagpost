"""End-to-end: the real KubernetesProvisioner against a live k3s (#320).

OPT-IN. Skipped unless ``FLAGPOST_E2E_K8S_ENDPOINT`` is set, and it lives in
``tests_e2e/`` — outside ``pytest.ini``'s ``testpaths=tests`` — so the normal
suite and CI never collect it. ``scripts/e2e-instances-k8s.sh`` boots k3s in
Docker, applies the RBAC, mints a token, and runs this with the cluster in the
environment.

Unlike the MockTransport unit tests, this hits a real API server with a real
CNI, so it proves the things a mock can't: the manifests are accepted, the RBAC
posture is exactly what we claim, a policy-enforcing CNI actually BLOCKS egress,
and a per-instance subdomain routes through Ingress.
"""

from __future__ import annotations

import asyncio
import os
import secrets

import httpx
import pytest

from utils.provisioner_kubernetes import KubernetesConfig, KubernetesProvisioner
from utils.provisioners import ProvisionSpec

ENDPOINT = os.environ.get("FLAGPOST_E2E_K8S_ENDPOINT")

pytestmark = pytest.mark.skipif(
    not ENDPOINT,
    reason="k8s e2e is opt-in — set FLAGPOST_E2E_K8S_ENDPOINT (see scripts/e2e-instances-k8s.sh)",
)

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


def _config(**over) -> KubernetesConfig:
    base = dict(
        endpoint_url=ENDPOINT,
        token=os.environ["FLAGPOST_E2E_K8S_TOKEN"],
        namespace="flagpost-instances",
        public_host=os.environ.get("FLAGPOST_E2E_K8S_PUBLIC_HOST", "127.0.0.1"),
        chal_base_domain=os.environ.get("FLAGPOST_E2E_K8S_BASE_DOMAIN", ""),
        ca_cert=os.environ.get("FLAGPOST_E2E_K8S_CA") or None,
    )
    base.update(over)
    return KubernetesConfig(**base)


async def test_validate_all_legs_pass_on_real_k3s():
    prov = KubernetesProvisioner(_config())
    legs = await prov.validate()
    report = "\n".join(f"  [{'ok' if l.ok else 'FAIL'}] {l.name}: {l.detail}" for l in legs)
    print("\nvalidate():\n" + report)

    by = {l.name: l for l in legs}
    # The security-critical legs must pass on a correctly-bootstrapped cluster.
    for name in ("endpoint_reachable", "privilege_posture", "namespace_ready",
                 "network_policy_support", "egress_enforcement", "probe_run",
                 "public_reachable"):
        assert name in by, f"missing leg {name}\n{report}"
        assert by[name].ok, f"leg {name} failed:\n{report}"
    # The honest one: k3s's embedded kube-router enforces NetworkPolicy, so a
    # deny-all-egress pod must be BLOCKED — this is the whole point of the leg.
    assert by["egress_enforcement"].ok
    # http_ingress runs because the harness sets a base domain.
    if "http_ingress" in by:
        assert by["http_ingress"].ok, f"http_ingress failed:\n{report}"


async def test_cluster_admin_token_fails_posture():
    """A deliberately over-privileged token must FAIL the posture leg — the leg
    is only meaningful if it actually rejects one."""
    admin_token = os.environ.get("FLAGPOST_E2E_K8S_ADMIN_TOKEN")
    if not admin_token:
        pytest.skip("set FLAGPOST_E2E_K8S_ADMIN_TOKEN to a cluster-admin token to check the negative")
    prov = KubernetesProvisioner(_config(token=admin_token))
    legs = {l.name: l for l in await prov.validate()}
    assert legs["privilege_posture"].ok is False


async def test_http_instance_routes_through_ingress():
    """Create a whoami instance with http exposure and reach it at its
    per-instance subdomain through k3s's Traefik, then tear it down."""
    subdomain = "e2e" + "".join(secrets.choice(_ALPHABET) for _ in range(5))
    base = os.environ.get("FLAGPOST_E2E_K8S_BASE_DOMAIN", "chal.127.0.0.1.sslip.io")
    prov = KubernetesProvisioner(_config(chal_base_domain=base))
    spec = ProvisionSpec(
        instance_id=f"e2e-{subdomain}",
        deployment_id="e2e",
        challenge_id="e2e",
        competition_id="e2e",
        image_ref="traefik/whoami:latest",
        manifest=None,
        exposure="http",
        ports=[80],
        env={},
        resource_limits={"cpu": 0.25, "memory_mb": 64},
        lifetime_s=600,
        subject_key="e2e",
        subdomain=subdomain,
    )
    handle = await prov.create(spec)
    try:
        assert await prov.status(handle) == "running"
        url = f"http://{subdomain}.{base}/"
        got = ""
        async with httpx.AsyncClient(timeout=5.0) as http:
            for _ in range(20):
                try:
                    resp = await http.get(url)
                    if resp.status_code == 200 and "Hostname:" in resp.text:
                        got = resp.text
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(2)
        assert got, f"instance was not reachable at {url} within the timeout"
    finally:
        await prov.destroy(handle)
    # destroy is idempotent — a second call is a clean no-op.
    await prov.destroy(handle)
