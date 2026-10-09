"""KubernetesProvisioner (#320, ADR-0036 §1) — unit-tested with a mocked httpx
transport, so the hardened manifests and the whole lifecycle are exercised
without a live cluster (the DockerProvisioner MockTransport pattern).

The manifest assertions are the security crux: every privileged pod field must
be pinned by Flagpost regardless of what a challenge author supplies.
"""

import json

import httpx
import pytest

from utils.provisioner_kubernetes import (
    _POSTURE_ALLOW,
    LABEL_MANAGED,
    KubernetesConfig,
    KubernetesProvisioner,
)
from utils.provisioners import ProvisionSpec, ProvisionerError


async def _nosleep(_seconds: float) -> None:
    return None


def _cfg(**over) -> KubernetesConfig:
    base = dict(
        endpoint_url="https://k8s.internal:6443",
        token="sa-token",
        namespace="flagpost-instances",
        public_host="chal.example.org",
    )
    base.update(over)
    return KubernetesConfig(**base)


def _spec(**over) -> ProvisionSpec:
    base = dict(
        instance_id="inst-1",
        deployment_id="dep-1",
        challenge_id="chal-1",
        competition_id="comp-1",
        image_ref="ghcr.io/example/pwn:1",
        manifest=None,
        exposure="tcp",
        ports=[1337],
        env={"DIFFICULTY": "hard"},
        resource_limits=None,
        lifetime_s=1800,
        subject_key="team-9",
        host_ports={1337: 30001},
    )
    base.update(over)
    return ProvisionSpec(**base)


class _Router:
    """A (method, matcher) -> Response|callable router for MockTransport,
    recording every request. ``matcher`` is a substring or a predicate."""

    def __init__(self):
        self.routes: list[tuple[str, object, object]] = []
        self.requests: list[httpx.Request] = []

    def on(self, method: str, matcher, response):
        self.routes.append((method.upper(), matcher, response))
        return self

    def _matches(self, matcher, request) -> bool:
        if callable(matcher):
            return matcher(request)
        return matcher in request.url.path

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            for method, matcher, response in self.routes:
                if request.method == method and self._matches(matcher, request):
                    return response(request) if callable(response) else response
            return httpx.Response(
                500, json={"message": f"unrouted {request.method} {request.url.path}"}
            )

        return httpx.MockTransport(handler)

    def body(self, method: str, contains: str) -> dict:
        for r in self.requests:
            if r.method == method.upper() and contains in r.url.path:
                return json.loads(r.content)
        raise AssertionError(f"no {method} request to …{contains} captured")

    def saw(self, method: str, contains: str) -> bool:
        return any(
            r.method == method.upper() and contains in r.url.path
            for r in self.requests
        )


def _ready_deploy(request):
    return httpx.Response(200, json={"status": {"readyReplicas": 1}})


def _happy_create_router() -> _Router:
    return (
        _Router()
        .on("POST", "/deployments", httpx.Response(201, json={"metadata": {"name": "flagpost-inst-inst-1"}}))
        .on("POST", "/networkpolicies", httpx.Response(201, json={}))
        .on("POST", "/services", httpx.Response(201, json={}))
        .on("POST", "/ingresses", httpx.Response(201, json={}))
        # GET the Deployment by name during the readiness wait → ready at once.
        .on("GET", lambda r: r.method == "GET" and "/deployments/flagpost-inst-" in r.url.path, _ready_deploy)
    )


# --- create: the hardened pod manifest --------------------------------------


async def test_create_composes_a_hardened_pod():
    router = _happy_create_router()
    prov = KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep)

    handle = await prov.create(_spec(flag_plaintext="flag{unique-1}"))
    assert handle == "flagpost-inst-inst-1"

    body = router.body("POST", "/deployments")
    pod = body["spec"]["template"]["spec"]
    container = pod["containers"][0]
    sc = container["securityContext"]
    # Privilege hardening — fixed, never author-controlled.
    assert sc["capabilities"]["drop"] == ["ALL"]
    assert sc["allowPrivilegeEscalation"] is False
    assert sc["privileged"] is False
    assert sc["readOnlyRootFilesystem"] is True
    # K8s-only pins.
    assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
    assert pod["automountServiceAccountToken"] is False
    assert pod["enableServiceLinks"] is False
    # A zero-rights, explicitly-named SA (no default-SA race), token not mounted.
    assert pod["serviceAccountName"] == "flagpost-instance"
    # Scratch /tmp is an emptyDir, not the read-only rootfs.
    assert pod["volumes"][0]["emptyDir"]["sizeLimit"] == "64Mi"
    assert container["volumeMounts"][0]["mountPath"] == "/tmp"
    # requests == limits (hard ceiling, no burst).
    assert container["resources"]["requests"] == container["resources"]["limits"]
    # In-cluster health check on the primary port.
    assert container["livenessProbe"]["tcpSocket"]["port"] == 1337
    # The unique flag is injected as env (in memory), never persisted.
    assert {"name": "FLAG", "value": "flag{unique-1}"} in container["env"]
    # Auth header carried the bearer token.
    dep_req = next(r for r in router.requests if r.method == "POST" and "/deployments" in r.url.path)
    assert dep_req.headers["Authorization"] == "Bearer sa-token"


async def test_create_tcp_requests_the_allocated_nodeport():
    router = _happy_create_router()
    prov = KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep)
    await prov.create(_spec(host_ports={1337: 30001}))

    svc = router.body("POST", "/services")
    assert svc["spec"]["type"] == "NodePort"
    port = svc["spec"]["ports"][0]
    assert port["nodePort"] == 30001 and port["port"] == 1337
    # A TCP instance is not an Ingress.
    assert not router.saw("POST", "/ingresses")


async def test_create_none_lays_down_only_a_deployment():
    # exposure="none" (unique-flag holder / bot-visited) → Deployment only; a
    # zero-port Service is invalid, so no Service and no Ingress are posted.
    router = _happy_create_router()
    prov = KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep)
    handle = await prov.create(_spec(exposure="none", ports=[], host_ports={}))
    assert handle == "flagpost-inst-inst-1"
    assert router.saw("POST", "/deployments")
    assert not router.saw("POST", "/services")
    assert not router.saw("POST", "/ingresses")
    # No ports ⇒ no livenessProbe on the container.
    pod = router.body("POST", "/deployments")["spec"]["template"]["spec"]
    assert "livenessProbe" not in pod["containers"][0]


async def test_multi_port_service_names_every_port():
    router = _happy_create_router()
    prov = KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep)
    await prov.create(_spec(ports=[1337, 8080], host_ports={1337: 30001, 8080: 30002}))
    svc_ports = router.body("POST", "/services")["spec"]["ports"]
    names = [p["name"] for p in svc_ports]
    # Every port is named and the names are unique (k8s requires this for >1).
    assert names == ["p-1337", "p-8080"]
    assert len(set(names)) == len(names)


async def test_transient_readiness_error_is_absorbed_not_leaked():
    # A blip on one readiness poll must NOT abort create() or leak objects — the
    # loop keeps polling and the next GET finds the replica ready.
    calls = {"n": 0}

    def get_deploy(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection reset", request=request)
        return httpx.Response(200, json={"status": {"readyReplicas": 1}})

    router = (
        _Router()
        .on("POST", "/deployments", httpx.Response(201, json={"metadata": {"name": "flagpost-inst-inst-1"}}))
        .on("POST", "/networkpolicies", httpx.Response(201, json={}))
        .on("POST", "/services", httpx.Response(201, json={}))
        .on("GET", lambda r: "/deployments/flagpost-inst-" in r.url.path, get_deploy)
        .on("DELETE", "/", httpx.Response(200, json={}))
    )
    prov = KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep, ready_attempts=3)
    handle = await prov.create(_spec())
    assert handle == "flagpost-inst-inst-1"
    # The blip was absorbed — nothing was torn down.
    assert not router.saw("DELETE", "/deployments/flagpost-inst-inst-1")


async def test_create_http_lays_down_clusterip_and_ingress():
    router = _happy_create_router()
    prov = KubernetesProvisioner(
        _cfg(chal_base_domain="chal.example.org", ingress_class="traefik"),
        transport=router.transport(),
        sleep=_nosleep,
    )
    await prov.create(_spec(exposure="http", ports=[8080], subdomain="abcd2345", host_ports={}))

    svc = router.body("POST", "/services")
    assert svc["spec"]["type"] == "ClusterIP"
    assert svc["spec"]["ports"][0]["port"] == 8080

    ing = router.body("POST", "/ingresses")
    rule = ing["spec"]["rules"][0]
    assert rule["host"] == "abcd2345.chal.example.org"
    assert rule["http"]["paths"][0]["backend"]["service"]["port"]["number"] == 8080
    assert ing["spec"]["ingressClassName"] == "traefik"


async def test_create_http_refuses_without_subdomain_or_base_domain():
    # No base domain configured → the ingress body can't be composed.
    router = _happy_create_router()
    prov = KubernetesProvisioner(_cfg(chal_base_domain=""), transport=router.transport(), sleep=_nosleep)
    with pytest.raises(ProvisionerError, match="subdomain or base domain"):
        await prov.create(_spec(exposure="http", ports=[8080], subdomain="abcd2345", host_ports={}))


async def test_create_refuses_without_an_image():
    prov = KubernetesProvisioner(_cfg(), transport=_Router().transport(), sleep=_nosleep)
    with pytest.raises(ProvisionerError, match="no image reference"):
        await prov.create(_spec(image_ref=None))


async def test_image_pull_secret_is_stamped_when_configured():
    router = _happy_create_router()
    prov = KubernetesProvisioner(
        _cfg(image_pull_secret="flagpost-pull"), transport=router.transport(), sleep=_nosleep
    )
    await prov.create(_spec())
    pod = router.body("POST", "/deployments")["spec"]["template"]["spec"]
    assert pod["imagePullSecrets"] == [{"name": "flagpost-pull"}]


# --- NetworkPolicy isolation (#320 D5) --------------------------------------


def _netpol_body(router: _Router) -> dict:
    return router.body("POST", "/networkpolicies")["spec"]


async def test_create_always_lays_down_a_networkpolicy():
    router = _happy_create_router()
    prov = KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep)
    await prov.create(_spec())
    assert router.saw("POST", "/networkpolicies")
    spec = _netpol_body(router)
    assert spec["policyTypes"] == ["Ingress", "Egress"]
    assert spec["podSelector"]["matchLabels"]["flagpost.io/instance-id"] == "inst-1"


# DNS egress is scoped to the cluster DNS pods, not any host on port 53 (GHSA-vgrr).
_DNS_EGRESS = {
    "to": [
        {
            "namespaceSelector": {
                "matchLabels": {"kubernetes.io/metadata.name": "kube-system"}
            },
            "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
        }
    ],
    "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}],
}


async def test_deny_mode_egress_is_dns_only():
    router = _happy_create_router()
    prov = KubernetesProvisioner(_cfg(egress_denied=True), transport=router.transport(), sleep=_nosleep)
    await prov.create(_spec(ports=[1337], host_ports={1337: 30001}))
    spec = _netpol_body(router)
    # Egress: DNS to kube-dns only — no ipBlock, and no egress-to-any on port 53.
    assert spec["egress"] == [_DNS_EGRESS]
    # Ingress: the declared container port from any source.
    assert spec["ingress"] == [{"ports": [{"protocol": "TCP", "port": 1337}]}]


def _ipblocks_by_family(egress: list) -> dict[str, dict]:
    # The DNS rule now also has a "to" (a pod/namespace selector), so pick the
    # rule whose "to" carries ipBlocks, not the DNS rule.
    blocks = next(r for r in egress if r.get("to") and "ipBlock" in r["to"][0])["to"]
    return {b["ipBlock"]["cidr"]: b["ipBlock"] for b in blocks}


async def test_allow_mode_egress_excepts_metadata_and_cluster_cidrs():
    router = _happy_create_router()
    prov = KubernetesProvisioner(
        _cfg(egress_denied=False, cluster_cidr="10.42.0.0/16,10.43.0.0/16"),
        transport=router.transport(),
        sleep=_nosleep,
    )
    await prov.create(_spec())
    egress = _netpol_body(router)["egress"]
    # DNS is still carved in (scoped to kube-dns).
    assert _DNS_EGRESS in egress
    blocks = _ipblocks_by_family(egress)
    # The IPv4 block excepts the metadata IP + both (IPv4) cluster ranges.
    assert set(blocks["0.0.0.0/0"]["except"]) == {"169.254.169.254/32", "10.42.0.0/16", "10.43.0.0/16"}


async def test_allow_mode_partitions_dual_stack_cluster_cidrs():
    # An IPv6 cluster range must NOT be crammed into the IPv4 0.0.0.0/0 block
    # (the apiserver rejects a cross-family except) — it belongs in the ::/0
    # block. This is the fix for the dual-stack rejection.
    router = _happy_create_router()
    prov = KubernetesProvisioner(
        _cfg(egress_denied=False, cluster_cidr="10.42.0.0/16,fd00:10:96::/112"),
        transport=router.transport(),
        sleep=_nosleep,
    )
    await prov.create(_spec())
    blocks = _ipblocks_by_family(_netpol_body(router)["egress"])
    assert set(blocks["0.0.0.0/0"]["except"]) == {"169.254.169.254/32", "10.42.0.0/16"}
    assert set(blocks["::/0"]["except"]) == {"fd00:ec2::254/128", "fd00:10:96::/112"}


async def test_allow_mode_always_blocks_both_metadata_ips():
    # Even with no cluster_cidr, both the v4 and v6 metadata IPs are excepted and
    # the IPv6 half is not left wide open.
    router = _happy_create_router()
    prov = KubernetesProvisioner(_cfg(egress_denied=False), transport=router.transport(), sleep=_nosleep)
    await prov.create(_spec())
    blocks = _ipblocks_by_family(_netpol_body(router)["egress"])
    assert blocks["0.0.0.0/0"]["except"] == ["169.254.169.254/32"]
    assert blocks["::/0"]["except"] == ["fd00:ec2::254/128"]


async def test_networkpolicy_create_failure_aborts_before_the_pod():
    # The security-load-bearing invariant: if the NetworkPolicy can't be created,
    # provisioning aborts — a deliberately-vulnerable pod must NEVER run without
    # its isolation. Since the netpol is posted first, the Deployment is never
    # even created.
    router = (
        _Router()
        .on("POST", "/networkpolicies", httpx.Response(403, json={"message": "forbidden"}))
        .on("POST", "/deployments", httpx.Response(201, json={"metadata": {"name": "flagpost-inst-inst-1"}}))
        .on("DELETE", "/", httpx.Response(200, json={}))
    )
    prov = KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep)
    with pytest.raises(ProvisionerError, match="network policy create failed"):
        await prov.create(_spec())
    assert not router.saw("POST", "/deployments")


async def test_exposure_none_networkpolicy_denies_all_ingress():
    router = _happy_create_router()
    prov = KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep)
    await prov.create(_spec(exposure="none", ports=[], host_ports={}))
    # Still isolated, and nothing may reach it (empty ingress = deny-all-in).
    assert router.saw("POST", "/networkpolicies")
    assert _netpol_body(router)["ingress"] == []


# --- create: failure cleans up partial resources ----------------------------


async def test_service_create_failure_tears_down_the_deployment():
    router = (
        _Router()
        .on("POST", "/deployments", httpx.Response(201, json={"metadata": {"name": "flagpost-inst-inst-1"}}))
        .on("POST", "/networkpolicies", httpx.Response(201, json={}))
        .on("POST", "/services", httpx.Response(409, json={"message": "nodePort 30001 already allocated"}))
        .on("DELETE", "/", httpx.Response(200, json={}))
    )
    prov = KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep)
    with pytest.raises(ProvisionerError, match="service create failed"):
        await prov.create(_spec())
    # The already-created Deployment was cleaned up.
    assert router.saw("DELETE", "/deployments/flagpost-inst-inst-1")


async def test_never_ready_reports_pod_reason_and_cleans_up():
    router = (
        _Router()
        .on("POST", "/deployments", httpx.Response(201, json={"metadata": {"name": "flagpost-inst-inst-1"}}))
        .on("POST", "/networkpolicies", httpx.Response(201, json={}))
        .on("POST", "/services", httpx.Response(201, json={}))
        # Deployment never reports a ready replica.
        .on("GET", lambda r: "/deployments/flagpost-inst-" in r.url.path, httpx.Response(200, json={"status": {"readyReplicas": 0}}))
        # The pod is stuck pulling a bad image.
        .on("GET", "/pods", httpx.Response(200, json={
            "items": [{"status": {"containerStatuses": [
                {"state": {"waiting": {"reason": "ErrImagePull", "message": "not found"}}}
            ]}}]
        }))
        .on("DELETE", "/", httpx.Response(200, json={}))
    )
    prov = KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep, ready_attempts=3)
    with pytest.raises(ProvisionerError, match="ErrImagePull"):
        await prov.create(_spec())
    # A never-ready instance is not left behind.
    assert router.saw("DELETE", "/deployments/flagpost-inst-inst-1")


# --- status / endpoints / destroy / list ------------------------------------


async def test_status_maps_ready_replicas():
    ready = _Router().on("GET", "/deployments/", httpx.Response(200, json={"status": {"readyReplicas": 1}}))
    starting = _Router().on("GET", "/deployments/", httpx.Response(200, json={"status": {"readyReplicas": 0}}))
    gone = _Router().on("GET", "/deployments/", httpx.Response(404, json={"message": "not found"}))
    assert await KubernetesProvisioner(_cfg(), transport=ready.transport()).status("h") == "running"
    assert await KubernetesProvisioner(_cfg(), transport=starting.transport()).status("h") == "stopped"
    assert await KubernetesProvisioner(_cfg(), transport=gone.transport()).status("h") == "unknown"


async def test_endpoints_reads_back_the_nodeport():
    router = _Router().on("GET", "/services/", httpx.Response(200, json={
        "spec": {"type": "NodePort", "ports": [{"nodePort": 30001}]}
    }))
    eps = await KubernetesProvisioner(_cfg(), transport=router.transport()).endpoints("h")
    assert eps == [{"kind": "tcp", "host": "chal.example.org", "port": 30001}]


async def test_endpoints_empty_for_clusterip_http():
    # ClusterIP (http) yields no tcp endpoint — the planned https URL stands.
    router = _Router().on("GET", "/services/", httpx.Response(200, json={"spec": {"type": "ClusterIP", "ports": [{"port": 8080}]}}))
    assert await KubernetesProvisioner(_cfg(), transport=router.transport()).endpoints("h") == []


async def test_destroy_sweeps_all_kinds_and_tolerates_404():
    seen: list[str] = []

    def rec(request):
        seen.append(request.url.path)
        # NetworkPolicy never existed for this instance → 404, tolerated.
        code = 404 if "/networkpolicies/" in request.url.path else 200
        return httpx.Response(code, json={})

    router = _Router().on("DELETE", "/", rec)
    await KubernetesProvisioner(_cfg(), transport=router.transport()).destroy("flagpost-inst-x")
    # All four object kinds are swept by the shared name.
    assert any("/deployments/flagpost-inst-x" in p for p in seen)
    assert any("/services/flagpost-inst-x" in p for p in seen)
    assert any("/ingresses/flagpost-inst-x" in p for p in seen)
    assert any("/networkpolicies/flagpost-inst-x" in p for p in seen)


async def test_destroy_raises_on_a_real_failure():
    router = _Router().on("DELETE", "/", httpx.Response(500, json={"message": "boom"}))
    with pytest.raises(ProvisionerError, match="teardown failed"):
        await KubernetesProvisioner(_cfg(), transport=router.transport()).destroy("flagpost-inst-x")


async def test_list_returns_managed_deployment_names():
    captured = {}

    def handler(request):
        captured["selector"] = request.url.params.get("labelSelector")
        return httpx.Response(200, json={"items": [
            {"metadata": {"name": "flagpost-inst-a"}},
            {"metadata": {"name": "flagpost-inst-b"}},
        ]})

    router = _Router().on("GET", lambda r: r.url.path.endswith("/deployments"), handler)
    names = await KubernetesProvisioner(_cfg(), transport=router.transport()).list()
    assert names == ["flagpost-inst-a", "flagpost-inst-b"]
    assert captured["selector"] == f"{LABEL_MANAGED}=true"


# --- validate() short-circuit legs (full staged run tested below) -----------


async def test_validate_flags_a_rejected_token():
    router = _Router().on("GET", "/version", httpx.Response(401, json={"message": "Unauthorized"}))
    legs = await KubernetesProvisioner(_cfg(), transport=router.transport()).validate()
    assert legs[0].name == "endpoint_reachable" and legs[0].ok is False
    assert "token" in legs[0].detail
    # A failed first leg short-circuits.
    assert len(legs) == 1


async def test_validate_flags_an_inoperable_namespace():
    # A good token (posture passes) but the namespace list is forbidden.
    router = _validate_router(namespace_ok=False)
    legs = await KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep).validate()
    ns = next(l for l in legs if l.name == "namespace_ready")
    assert ns.ok is False


# --- staged validate() (#320 D8) --------------------------------------------


def _ssar_handler(*, cluster_admin: bool = False, denied_rights: frozenset = frozenset()):
    """SelfSubjectAccessReview responder. A good namespace-scoped token allows
    exactly the _POSTURE_ALLOW set (minus any ``denied_rights``) and denies
    everything else; a cluster-admin token allows everything (failing the deny
    checks)."""
    allow_keys = {(v, g, r, s) for (v, g, r, s) in _POSTURE_ALLOW} - set(denied_rights)

    def handler(request):
        attrs = json.loads(request.content)["spec"]["resourceAttributes"]
        key = (attrs["verb"], attrs.get("group", ""), attrs["resource"], attrs.get("subresource", ""))
        allowed = True if cluster_admin else (key in allow_keys)
        return httpx.Response(201, json={"status": {"allowed": allowed}})

    return handler


def _validate_router(
    *, cluster_admin: bool = False, egress_exit: int | None = 1, baseline_exit: int = 0,
    probe_running: bool = True, denied_rights: frozenset = frozenset(), namespace_ok: bool = True,
) -> _Router:
    """A router covering every call the staged validate() makes, with all legs
    green by default (good token, netpol accepted, egress enforced — deny-all
    blocks, unrestricted baseline reaches — and the probe pod up)."""
    def pods_get(request):
        p = request.url.path
        if p.endswith("/flagpost-egress-probe"):  # phase 1: under deny-all policy
            cs = [] if egress_exit is None else [{"state": {"terminated": {"exitCode": egress_exit}}}]
            return httpx.Response(200, json={"status": {"phase": "Failed", "containerStatuses": cs}})
        if p.endswith("/flagpost-egress-baseline"):  # phase 2: no policy (positive control)
            return httpx.Response(200, json={"status": {"phase": "Succeeded", "containerStatuses": [
                {"state": {"terminated": {"exitCode": baseline_exit}}}]}})
        if p.endswith("/flagpost-probe"):
            phase = "Running" if probe_running else "Pending"
            return httpx.Response(200, json={"status": {"phase": phase}})
        return httpx.Response(404, json={"message": "not found"})

    ns_resp = (
        httpx.Response(200, json={"items": []}) if namespace_ok
        else httpx.Response(403, json={"message": "forbidden"})
    )
    return (
        _Router()
        .on("GET", "/version", httpx.Response(200, json={"gitVersion": "v1.30.2"}))
        .on("POST", "/selfsubjectaccessreviews", _ssar_handler(cluster_admin=cluster_admin, denied_rights=denied_rights))
        .on("GET", lambda r: r.url.path.endswith("/deployments"), ns_resp)
        .on("POST", "/networkpolicies", httpx.Response(201, json={}))
        .on("POST", "/pods", httpx.Response(201, json={}))
        .on("POST", "/services", httpx.Response(201, json={}))
        .on("GET", lambda r: "/pods/flagpost" in r.url.path, pods_get)
        .on("GET", lambda r: "/services/flagpost-probe" in r.url.path,
            httpx.Response(200, json={"spec": {"ports": [{"nodePort": 31234}]}}))
        .on("DELETE", "/", httpx.Response(200, json={}))
    )


async def _yes_dial(host, port):
    return True


async def _no_dial(host, port):
    return False


def _leg(legs, name):
    return next(l for l in legs if l.name == name)


async def test_validate_all_legs_pass():
    router = _validate_router()
    prov = KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep, tcp_probe=_yes_dial)
    legs = await prov.validate()
    names = [l.name for l in legs]
    assert names == [
        "endpoint_reachable", "privilege_posture", "namespace_ready",
        "network_policy_support", "egress_enforcement", "probe_run", "public_reachable",
    ]
    assert all(l.ok for l in legs), [(l.name, l.detail) for l in legs if not l.ok]


async def test_validate_posture_rejects_an_overprivileged_token():
    # A cluster-admin token is allowed the dangerous verbs → posture fails and
    # the run short-circuits (no probe pods driven through it).
    router = _validate_router(cluster_admin=True)
    prov = KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep, tcp_probe=_yes_dial)
    legs = await prov.validate()
    posture = _leg(legs, "privilege_posture")
    assert posture.ok is False
    assert "over-privileged" in posture.detail
    # Short-circuited: nothing after posture ran.
    assert [l.name for l in legs] == ["endpoint_reachable", "privilege_posture"]


async def test_validate_posture_flags_a_missing_right():
    # Deny a required right (create networkpolicies) → posture fails.
    router = _validate_router(
        denied_rights=frozenset({("create", "networking.k8s.io", "networkpolicies", "")})
    )
    legs = await KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep).validate()
    posture = _leg(legs, "privilege_posture")
    assert posture.ok is False
    assert "DENIED" in posture.detail and "networkpolicies" in posture.detail


async def test_validate_detects_a_non_enforcing_cni():
    # The deny-all-egress probe REACHES the internet (exit 0) → the CNI is not
    # enforcing NetworkPolicy: the silent-security-failure this leg exists for.
    router = _validate_router(egress_exit=0)
    prov = KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep, tcp_probe=_yes_dial)
    legs = await prov.validate()
    egress = _leg(legs, "egress_enforcement")
    assert egress.ok is False
    assert "not enforcing" in egress.detail
    # The egress probe pod + its policy are always cleaned up.
    assert router.saw("DELETE", "/pods/flagpost-egress-probe")
    assert router.saw("DELETE", "/networkpolicies/flagpost-egress-probe")


async def test_validate_egress_inconclusive_when_node_has_no_internet():
    # Deny-all blocks (exit 1) but so does the unrestricted baseline (exit 1):
    # the node has no route to the target, so enforcement can't be measured — a
    # PASS here would be a false green (the air-gapped false-positive).
    router = _validate_router(egress_exit=1, baseline_exit=1)
    prov = KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep, tcp_probe=_yes_dial)
    legs = await prov.validate()
    egress = _leg(legs, "egress_enforcement")
    assert egress.ok is False and "inconclusive" in egress.detail
    # The positive-control baseline pod ran and was cleaned up.
    assert router.saw("DELETE", "/pods/flagpost-egress-baseline")


async def test_validate_egress_inconclusive_when_exit_code_unreadable():
    # The deny-all pod reached a terminal phase but produced no exit code
    # (evicted / OOM / status race): the probe never tested egress, so the leg
    # must NOT claim enforcement.
    router = _validate_router(egress_exit=None)
    prov = KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep, tcp_probe=_yes_dial)
    legs = await prov.validate()
    egress = _leg(legs, "egress_enforcement")
    assert egress.ok is False and "did not report a result" in egress.detail
    # No positive-control baseline pod is created when phase 1 is inconclusive.
    posted_pod_names = [
        json.loads(r.content).get("metadata", {}).get("name")
        for r in router.requests
        if r.method == "POST" and r.url.path.endswith("/pods")
    ]
    assert "flagpost-egress-baseline" not in posted_pod_names


async def test_validate_flags_unreachable_public_host():
    router = _validate_router()
    prov = KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep, tcp_probe=_no_dial)
    legs = await prov.validate()
    reach = _leg(legs, "public_reachable")
    assert reach.ok is False and "NOT reachable" in reach.detail
    # The probe pod + service are cleaned up regardless.
    assert router.saw("DELETE", "/pods/flagpost-probe")
    assert router.saw("DELETE", "/services/flagpost-probe")


async def test_validate_adds_http_ingress_leg_when_base_domain_set():
    async def http_ok(fqdn):
        return True, f"{fqdn} resolves and the ingress answers on :443"

    router = _validate_router()
    prov = KubernetesProvisioner(
        _cfg(chal_base_domain="chal.example.org"),
        transport=router.transport(), sleep=_nosleep, tcp_probe=_yes_dial, http_probe=http_ok,
    )
    legs = await prov.validate()
    http = _leg(legs, "http_ingress")
    assert http.ok is True


async def test_validate_no_http_leg_without_base_domain():
    router = _validate_router()
    prov = KubernetesProvisioner(_cfg(), transport=router.transport(), sleep=_nosleep, tcp_probe=_yes_dial)
    legs = await prov.validate()
    assert not any(l.name == "http_ingress" for l in legs)
