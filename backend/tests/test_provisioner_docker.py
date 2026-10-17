"""DockerProvisioner (#266, ADR-0036 §1) — unit-tested with a mocked httpx
transport and a fake TCP dialer, so the hardened create payload, the lifecycle
calls, and the whole staged validate() run are exercised without a real Docker
daemon (the utils/ai/client.py MockTransport pattern).

The create-body assertions are the security crux: every privileged field must
be pinned by Flagpost regardless of what a challenge author supplies.
"""

import base64
import json

import httpx
import pytest

from utils.provisioner_docker import (
    LABEL_MANAGED,
    DockerConfig,
    DockerProvisioner,
    credential_registry_host,
    image_registry_host,
)
from utils.provisioners import ProvisionSpec, ProvisionerError


def _cfg(**over) -> DockerConfig:
    base = dict(
        endpoint_url="http://docker-proxy:2375",
        public_host="chal.example.org",
        network="flagpost-instances",
        probe_image="alpine:3.20",
    )
    base.update(over)
    return DockerConfig(**base)


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
    """A tiny (method, path-substring) -> Response|callable router for
    MockTransport, recording every request for assertions."""

    def __init__(self):
        self.routes: list[tuple[str, str, object]] = []
        self.requests: list[httpx.Request] = []

    def on(self, method: str, contains: str, response):
        self.routes.append((method.upper(), contains, response))
        return self

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            for method, contains, response in self.routes:
                if request.method == method and contains in request.url.path:
                    return response(request) if callable(response) else response
            # Default: a successful image pull. create() pulls before creating
            # (an absent image would 404 the create), and most create tests don't
            # care about the pull — a test that does adds its own /images/create
            # route above, which wins by matching first.
            if request.method == "POST" and request.url.path.endswith("/images/create"):
                return httpx.Response(
                    200,
                    content=b'{"status":"Status: Downloaded newer image"}\n',
                )
            # Per-instance network calls succeed by default (GHSA-vgrr): a TCP
            # create makes its own bridge and destroy removes it. Tests that
            # assert the specifics add explicit routes, which win by matching first.
            if request.method == "POST" and request.url.path.endswith("/networks/create"):
                return httpx.Response(201, json={"Id": "net-default"})
            if request.method == "DELETE" and "/networks/" in request.url.path:
                return httpx.Response(204)
            return httpx.Response(500, json={"message": f"unrouted {request.method} {request.url.path}"})

        return httpx.MockTransport(handler)

    def create_body(self) -> dict:
        for r in self.requests:
            if r.method == "POST" and r.url.path.endswith("/containers/create"):
                return json.loads(r.content)
        raise AssertionError("no create request captured")

    def network_create_body(self) -> dict:
        for r in self.requests:
            if r.method == "POST" and r.url.path.endswith("/networks/create"):
                return json.loads(r.content)
        raise AssertionError("no network create request captured")

    def saw(self, method: str, contains: str) -> bool:
        return any(
            r.method == method.upper() and contains in r.url.path
            for r in self.requests
        )


# --- create: the hardening payload ------------------------------------------


async def test_create_composes_a_hardened_payload():
    router = (
        _Router()
        .on("POST", "/containers/create", httpx.Response(201, json={"Id": "deadbeef"}))
        .on("POST", "/start", httpx.Response(204))
    )
    prov = DockerProvisioner(_cfg(), transport=router.transport())

    handle = await prov.create(_spec(flag_plaintext="flag{unique-123}"))
    assert handle == "deadbeef"

    body = router.create_body()
    hc = body["HostConfig"]
    # Privilege hardening — fixed, never author-controlled.
    assert hc["CapDrop"] == ["ALL"]
    assert hc["SecurityOpt"] == ["no-new-privileges:true"]
    assert hc["Privileged"] is False
    assert hc["ReadonlyRootfs"] is True
    assert hc["AutoRemove"] is True
    assert hc["Binds"] == [] and hc["Mounts"] == []
    assert hc["RestartPolicy"] == {"Name": "no"}
    # Resource limits (defaults): 256 MiB in bytes, 1.0 CPU in nano units.
    assert hc["Memory"] == 256 * 1024 * 1024
    assert hc["NanoCpus"] == 1_000_000_000
    assert hc["PidsLimit"] == 256
    # Exposure: attached to its OWN per-instance bridge (GHSA-vgrr), port
    # published on bind_ip — a neighbour on another bridge has no route to it.
    assert hc["NetworkMode"] == "flagpost-net-inst-1"
    assert hc["PortBindings"] == {"1337/tcp": [{"HostIp": "0.0.0.0", "HostPort": "30001"}]}
    assert body["ExposedPorts"] == {"1337/tcp": {}}
    # Flag injected in-memory as env; author env preserved.
    assert "FLAG=flag{unique-123}" in body["Env"]
    assert "DIFFICULTY=hard" in body["Env"]
    # Labels tie the container to the row and mark it managed.
    assert body["Labels"][LABEL_MANAGED] == "true"
    assert body["Labels"]["io.flagpost.instance_id"] == "inst-1"
    # Container named for the instance.
    create_req = next(r for r in router.requests if r.url.path.endswith("/containers/create"))
    assert create_req.url.params["name"] == "flagpost-inst-inst-1"


async def test_create_pulls_the_image_before_creating():
    # An explicit pull route so we can assert the order and the pulled image.
    router = (
        _Router()
        .on("POST", "/images/create", httpx.Response(
            200, content=b'{"status":"Status: Downloaded newer image for ghcr.io/example/pwn:1"}\n'))
        .on("POST", "/containers/create", httpx.Response(201, json={"Id": "x"}))
        .on("POST", "/start", httpx.Response(204))
    )
    prov = DockerProvisioner(_cfg(), transport=router.transport())
    await prov.create(_spec())

    paths = [(r.method, r.url.path) for r in router.requests]
    pull_i = paths.index(("POST", "/images/create"))
    create_i = next(i for i, p in enumerate(paths) if p[1].endswith("/containers/create"))
    assert pull_i < create_i  # pulled before the container was created
    pull_req = router.requests[pull_i]
    assert pull_req.url.params["fromImage"] == "ghcr.io/example/pwn"
    assert pull_req.url.params["tag"] == "1"


async def test_create_fails_and_creates_nothing_when_the_pull_fails():
    router = (
        _Router()
        .on("POST", "/images/create", httpx.Response(
            200, content=b'{"status":"Pulling"}\n{"error":"manifest for ghcr.io/example/pwn:1 not found"}\n'))
        .on("POST", "/containers/create", httpx.Response(201, json={"Id": "should-not-happen"}))
    )
    prov = DockerProvisioner(_cfg(), transport=router.transport())
    with pytest.raises(ProvisionerError, match="image pull failed"):
        await prov.create(_spec())
    # A failed pull must not create a container.
    assert not router.saw("POST", "/containers/create")


async def test_create_resource_overrides_and_fractional_cpu():
    router = (
        _Router()
        .on("POST", "/containers/create", httpx.Response(201, json={"Id": "x"}))
        .on("POST", "/start", httpx.Response(204))
    )
    prov = DockerProvisioner(_cfg(), transport=router.transport())
    await prov.create(_spec(resource_limits={"cpu": 0.5, "memory_mb": 512, "pids": 64}))
    hc = router.create_body()["HostConfig"]
    assert hc["NanoCpus"] == 500_000_000  # 0.5 CPU
    assert hc["Memory"] == 512 * 1024 * 1024
    assert hc["PidsLimit"] == 64


@pytest.mark.parametrize(
    "limits",
    [
        # Raw stored values that int()-truncate to 0 — Docker's UNLIMITED. The
        # authoring schema now refuses them, but validate_shape isn't re-run at
        # provision time, so a row stored before that fix still carries them.
        {"cpu": 1e-10, "memory_mb": 0.5, "pids": 0.5},
        {"cpu": 0, "memory_mb": 0, "pids": 0},
        {"cpu": -1, "memory_mb": -1, "pids": -1},
    ],
)
async def test_create_clamps_stored_limits_that_would_mean_unlimited(limits):
    """GHSA-vgrr residual (defence in depth): the final runtime limits are
    clamped to the floors where they're composed, never 0."""
    router = (
        _Router()
        .on("POST", "/containers/create", httpx.Response(201, json={"Id": "x"}))
        .on("POST", "/start", httpx.Response(204))
    )
    prov = DockerProvisioner(_cfg(), transport=router.transport())
    await prov.create(_spec(resource_limits=limits))
    hc = router.create_body()["HostConfig"]
    assert hc["NanoCpus"] == 10_000_000  # 0.01 CPU, Docker's own minimum
    assert hc["Memory"] == 16 * 1024 * 1024
    assert hc["PidsLimit"] == 16


async def test_create_clamps_nan_caps_and_bad_operator_defaults():
    router = (
        _Router()
        .on("POST", "/containers/create", httpx.Response(201, json={"Id": "x"}))
        .on("POST", "/start", httpx.Response(204))
    )
    # A NaN override falls back to the operator default; an over-cap one is
    # capped; and an operator default that would itself mean unlimited is floored.
    prov = DockerProvisioner(
        _cfg(default_cpu=0.0, default_memory_mb=512, default_pids=0),
        transport=router.transport(),
    )
    await prov.create(_spec(resource_limits={"memory_mb": float("nan"), "pids": 10**9}))
    hc = router.create_body()["HostConfig"]
    assert hc["NanoCpus"] == 10_000_000  # default_cpu 0 → floor
    assert hc["Memory"] == 512 * 1024 * 1024  # NaN → default
    assert hc["PidsLimit"] == 65536  # capped


async def test_create_no_ports_uses_network_none():
    router = (
        _Router()
        .on("POST", "/containers/create", httpx.Response(201, json={"Id": "x"}))
        .on("POST", "/start", httpx.Response(204))
    )
    prov = DockerProvisioner(_cfg(), transport=router.transport())
    await prov.create(_spec(exposure="none", host_ports={}, ports=[]))
    body = router.create_body()
    assert body["HostConfig"]["NetworkMode"] == "none"
    assert "PortBindings" not in body["HostConfig"]
    assert "ExposedPorts" not in body


async def test_create_http_exposure_sets_caddy_labels_and_no_ports():
    router = (
        _Router()
        .on("POST", "/containers/create", httpx.Response(201, json={"Id": "web1"}))
        .on("POST", "/start", httpx.Response(204))
    )
    prov = DockerProvisioner(
        _cfg(chal_base_domain="chal.example.org"), transport=router.transport()
    )
    await prov.create(
        _spec(exposure="http", subdomain="k7m2q9xz", ports=[8080], host_ports={})
    )
    body = router.create_body()
    hc = body["HostConfig"]
    # On the shared bridge so the ingress can reach it; NO published host port.
    assert hc["NetworkMode"] == "flagpost-instances"
    assert "PortBindings" not in hc
    assert "ExposedPorts" not in body
    # caddy-docker-proxy labels route the per-instance subdomain to the container.
    assert body["Labels"]["caddy"] == "k7m2q9xz.chal.example.org"
    assert body["Labels"]["caddy.reverse_proxy"] == "{{upstreams 8080}}"


async def test_create_http_without_a_base_domain_refuses():
    prov = DockerProvisioner(_cfg(chal_base_domain=""))  # HTTP not configured
    with pytest.raises(ProvisionerError):
        prov._container_body(
            _spec(exposure="http", subdomain="k7m2q9xz", ports=[8080], host_ports={})
        )


async def test_create_without_image_refuses():
    prov = DockerProvisioner(_cfg(), transport=_Router().transport())
    with pytest.raises(ProvisionerError, match="no image"):
        await prov.create(_spec(image_ref=None))


async def test_create_cleans_up_when_start_fails():
    router = (
        _Router()
        .on("POST", "/containers/create", httpx.Response(201, json={"Id": "orphan"}))
        .on("POST", "/start", httpx.Response(500, json={"message": "oom"}))
        .on("DELETE", "/containers/", httpx.Response(204))
    )
    prov = DockerProvisioner(_cfg(), transport=router.transport())
    with pytest.raises(ProvisionerError, match="start failed"):
        await prov.create(_spec())
    # The created-but-not-running container was torn down, not leaked.
    assert router.saw("DELETE", "/containers/orphan")


# --- per-instance network isolation (GHSA-vgrr) ------------------------------


async def test_tcp_create_provisions_a_per_instance_bridge():
    router = (
        _Router()
        .on("POST", "/networks/create", httpx.Response(201, json={"Id": "net-a"}))
        .on("POST", "/containers/create", httpx.Response(201, json={"Id": "c1"}))
        .on("POST", "/start", httpx.Response(204))
    )
    prov = DockerProvisioner(_cfg(), transport=router.transport())
    await prov.create(_spec())

    # A dedicated normal bridge, named for the instance, labelled managed —
    # created BEFORE the container so it can attach at create time.
    net = router.network_create_body()
    assert net["Name"] == "flagpost-net-inst-1"
    assert net["Driver"] == "bridge"
    assert net["Internal"] is False  # an internal net can't publish a TCP port
    assert net["Labels"][LABEL_MANAGED] == "true"
    assert net["Labels"]["io.flagpost.instance_id"] == "inst-1"
    paths = [(r.method, r.url.path) for r in router.requests]
    net_i = paths.index(("POST", "/networks/create"))
    create_i = next(i for i, p in enumerate(paths) if p[1].endswith("/containers/create"))
    assert net_i < create_i
    # The container attaches to that per-instance bridge, not the shared one.
    assert router.create_body()["HostConfig"]["NetworkMode"] == "flagpost-net-inst-1"


async def test_http_create_stays_on_the_shared_bridge():
    # HTTP rides the shared caddy bridge (the ingress must share a net to reach
    # it), so NO per-instance network is created for it.
    router = (
        _Router()
        .on("POST", "/containers/create", httpx.Response(201, json={"Id": "web1"}))
        .on("POST", "/start", httpx.Response(204))
    )
    prov = DockerProvisioner(
        _cfg(chal_base_domain="chal.example.org"), transport=router.transport()
    )
    await prov.create(
        _spec(exposure="http", subdomain="k7m2q9xz", ports=[8080], host_ports={})
    )
    assert router.create_body()["HostConfig"]["NetworkMode"] == "flagpost-instances"
    assert not router.saw("POST", "/networks/create")


async def test_none_create_makes_no_network():
    router = (
        _Router()
        .on("POST", "/containers/create", httpx.Response(201, json={"Id": "x"}))
        .on("POST", "/start", httpx.Response(204))
    )
    prov = DockerProvisioner(_cfg(), transport=router.transport())
    await prov.create(_spec(exposure="none", host_ports={}, ports=[]))
    assert router.create_body()["HostConfig"]["NetworkMode"] == "none"
    assert not router.saw("POST", "/networks/create")


async def test_destroy_removes_the_per_instance_bridge():
    inspect = {"NetworkSettings": {"Networks": {"flagpost-net-inst-1": {}}}}
    router = (
        _Router()
        .on("GET", "/containers/c1/json", httpx.Response(200, json=inspect))
        .on("DELETE", "/containers/c1", httpx.Response(204))
        .on("DELETE", "/networks/flagpost-net-inst-1", httpx.Response(204))
    )
    prov = DockerProvisioner(_cfg(), transport=router.transport())
    await prov.destroy("c1")
    # Container removed, THEN its bridge (read off the container before removal).
    assert router.saw("DELETE", "/containers/c1")
    assert router.saw("DELETE", "/networks/flagpost-net-inst-1")
    paths = [(r.method, r.url.path) for r in router.requests]
    assert paths.index(("DELETE", "/containers/c1")) < paths.index(
        ("DELETE", "/networks/flagpost-net-inst-1")
    )


async def test_destroy_leaves_the_shared_bridge_alone():
    # A container on the shared bridge (an HTTP instance) must NOT trigger a
    # network removal — only per-instance flagpost-net-* bridges are ours to drop.
    inspect = {"NetworkSettings": {"Networks": {"flagpost-instances": {}}}}
    router = (
        _Router()
        .on("GET", "/containers/web1/json", httpx.Response(200, json=inspect))
        .on("DELETE", "/containers/web1", httpx.Response(204))
    )
    prov = DockerProvisioner(_cfg(), transport=router.transport())
    await prov.destroy("web1")
    assert not router.saw("DELETE", "/networks/")


async def test_destroy_survives_a_network_cleanup_failure():
    # The container is gone (what matters); a failed net delete only logs, so
    # destroy still returns cleanly and never leaves the instance "half-torn".
    inspect = {"NetworkSettings": {"Networks": {"flagpost-net-inst-1": {}}}}
    router = (
        _Router()
        .on("GET", "/containers/c1/json", httpx.Response(200, json=inspect))
        .on("DELETE", "/containers/c1", httpx.Response(204))
        .on("DELETE", "/networks/flagpost-net-inst-1", httpx.Response(500, json={"message": "boom"}))
    )
    prov = DockerProvisioner(_cfg(), transport=router.transport())
    await prov.destroy("c1")  # no raise despite the 500 on network removal


async def test_list_orphan_networks_finds_only_empty_managed_bridges():
    listing = [
        {"Name": "flagpost-net-a", "Id": "na"},      # managed, empty -> orphan
        {"Name": "flagpost-net-b", "Id": "nb"},      # managed, still has a container
        {"Name": "flagpost-instances", "Id": "ns"},  # shared, not per-instance
    ]
    router = (
        _Router()
        .on("GET", "/networks/na", httpx.Response(200, json={"Containers": {}}))
        .on("GET", "/networks/nb", httpx.Response(200, json={"Containers": {"c": {}}}))
        .on("GET", "/networks", httpx.Response(200, json=listing))
    )
    prov = DockerProvisioner(_cfg(), transport=router.transport())
    assert await prov.list_orphan_networks() == {"flagpost-net-a"}
    # The listing is scoped to managed networks by the label filter.
    listreq = next(
        r for r in router.requests
        if r.method == "GET" and r.url.path.endswith("/networks")
    )
    assert LABEL_MANAGED in listreq.url.params["filters"]


# --- status / endpoints / destroy / list ------------------------------------


async def test_status_maps_running_stopped_unknown():
    for state, expect in (
        ({"Running": True}, "running"),
        ({"Running": False, "Status": "exited"}, "stopped"),
    ):
        router = _Router().on("GET", "/containers/h/json", httpx.Response(200, json={"State": state}))
        prov = DockerProvisioner(_cfg(), transport=router.transport())
        assert await prov.status("h") == expect

    gone = _Router().on("GET", "/containers/h/json", httpx.Response(404, json={"message": "no such container"}))
    prov = DockerProvisioner(_cfg(), transport=gone.transport())
    assert await prov.status("h") == "unknown"


async def test_endpoints_reads_published_ports_and_uses_public_host():
    inspect = {
        "NetworkSettings": {"Ports": {"1337/tcp": [{"HostIp": "0.0.0.0", "HostPort": "30001"}]}}
    }
    router = _Router().on("GET", "/containers/h/json", httpx.Response(200, json=inspect))
    prov = DockerProvisioner(_cfg(), transport=router.transport())
    eps = await prov.endpoints("h")
    # Competitors get the PUBLIC host, not the container's bind IP.
    assert eps == [{"kind": "tcp", "host": "chal.example.org", "port": 30001}]


async def test_destroy_is_idempotent_on_404_but_raises_on_500():
    ok = _Router().on("DELETE", "/containers/h", httpx.Response(204))
    await DockerProvisioner(_cfg(), transport=ok.transport()).destroy("h")  # no raise

    gone = _Router().on("DELETE", "/containers/h", httpx.Response(404, json={"message": "gone"}))
    await DockerProvisioner(_cfg(), transport=gone.transport()).destroy("h")  # no raise

    broken = _Router().on("DELETE", "/containers/h", httpx.Response(500, json={"message": "boom"}))
    with pytest.raises(ProvisionerError, match="remove failed"):
        await DockerProvisioner(_cfg(), transport=broken.transport()).destroy("h")


async def test_list_filters_by_managed_label():
    router = _Router().on("GET", "/containers/json", httpx.Response(200, json=[{"Id": "a"}, {"Id": "b"}]))
    prov = DockerProvisioner(_cfg(), transport=router.transport())
    assert await prov.list() == ["a", "b"]
    # The filter is the managed label — the reaper never sees foreign containers.
    req = next(r for r in router.requests if r.url.path.endswith("/containers/json"))
    assert LABEL_MANAGED in req.url.params["filters"]


# --- validate(): the staged Test-connection ---------------------------------


def _healthy_router() -> _Router:
    """A proxy that is reachable, correctly restricting, and can run a probe."""
    return (
        _Router()
        .on("GET", "/_ping", httpx.Response(200, text="OK", headers={"Api-Version": "1.47"}))
        # posture: dangerous verbs correctly blocked by the proxy (403)
        .on("POST", "/exec", httpx.Response(403, text="Forbidden"))
        .on("GET", "/volumes", httpx.Response(403, text="Forbidden"))
        .on("POST", "/build", httpx.Response(403, text="Forbidden"))
        # the instance network exists as a normal bridge (the recommended config —
        # a TCP port can't be published from an internal network)
        .on("GET", "/networks/flagpost-instances", httpx.Response(200, json={"Internal": False}))
        # pull streams success NDJSON ending in the terminal Status line
        .on("POST", "/images/create", httpx.Response(200, content=b'{"status":"Pulling from library/alpine"}\n{"status":"Status: Downloaded newer image for alpine:3.20"}\n'))
        # probe run
        .on("POST", "/containers/create", httpx.Response(201, json={"Id": "probe1"}))
        .on("POST", "/start", httpx.Response(204))
        .on("GET", "/containers/probe1/json", httpx.Response(200, json={"NetworkSettings": {"Ports": {"45000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "39999"}]}}}))
        .on("DELETE", "/containers/probe1", httpx.Response(204))
    )


async def test_validate_all_green():
    router = _healthy_router()
    prov = DockerProvisioner(
        _cfg(), transport=router.transport(),
        tcp_probe=lambda host, port: _true(),
    )
    legs = await prov.validate()
    names = [leg.name for leg in legs]
    assert names == [
        "endpoint_reachable",
        "privilege_posture",
        "network_isolation",
        "image_pull",
        "probe_run",
        "public_reachable",
    ]
    assert all(leg.ok for leg in legs), [(l.name, l.detail) for l in legs]
    # The probe container was cleaned up.
    assert router.saw("DELETE", "/containers/probe1")
    # The reachability leg dialed the daemon-assigned port on the public host.
    assert "39999" in legs[-1].detail


async def test_validate_probe_exercises_the_per_instance_network_path():
    # The probe is exposure=tcp, so Test-connection now proves the whole
    # per-instance-bridge path works through the proxy (NETWORKS+POST): a bridge
    # is created for the probe and torn down with it (GHSA-vgrr).
    router = _healthy_router()
    prov = DockerProvisioner(
        _cfg(), transport=router.transport(), tcp_probe=lambda host, port: _true()
    )
    legs = await prov.validate()
    assert all(leg.ok for leg in legs)
    assert router.saw("POST", "/networks/create")
    assert router.saw("DELETE", "/networks/flagpost-net-probe")


async def test_validate_adds_http_leg_probing_the_wildcard_when_configured():
    router = _healthy_router()
    seen: dict = {}

    async def probe(fqdn: str) -> tuple[bool, str]:
        seen["fqdn"] = fqdn
        return True, "resolves and the ingress answers"

    prov = DockerProvisioner(
        _cfg(chal_base_domain="chal.example.org"),
        transport=router.transport(),
        tcp_probe=lambda h, p: _true(),
        http_probe=probe,
    )
    legs = await prov.validate()
    # A final http_ingress leg is appended, probing the synthetic wildcard subdomain.
    assert legs[-1].name == "http_ingress" and legs[-1].ok is True
    assert seen["fqdn"] == "http-probe.chal.example.org"


async def test_validate_http_leg_reports_a_dns_or_ingress_failure():
    router = _healthy_router()

    async def probe(fqdn: str) -> tuple[bool, str]:
        return False, "wildcard DNS did not resolve"

    prov = DockerProvisioner(
        _cfg(chal_base_domain="chal.example.org"),
        transport=router.transport(),
        tcp_probe=lambda h, p: _true(),
        http_probe=probe,
    )
    legs = await prov.validate()
    http = next(leg for leg in legs if leg.name == "http_ingress")
    assert http.ok is False and "DNS" in http.detail


async def test_validate_omits_http_leg_without_a_base_domain():
    router = _healthy_router()
    prov = DockerProvisioner(
        _cfg(), transport=router.transport(), tcp_probe=lambda h, p: _true()
    )
    legs = await prov.validate()
    assert "http_ingress" not in [leg.name for leg in legs]


async def test_posture_exec_probe_targets_the_exec_start_path():
    # The exec danger is blockable at POST /exec/<id>/start (the proxy's EXEC
    # flag → 403), NOT /containers/<id>/exec, which the proxy gates under
    # CONTAINERS (required for create/start/inspect) and therefore FORWARDS to
    # the daemon (400/404, never 403). Probing the container path reported a
    # false posture failure against a correctly-restricted socket proxy — caught
    # by testing against a real tecnativa/docker-socket-proxy.
    router = _healthy_router()
    prov = DockerProvisioner(_cfg(), transport=router.transport(), tcp_probe=lambda h, p: _true())
    await prov.validate()
    exec_reqs = [r for r in router.requests if "/exec" in r.url.path]
    assert exec_reqs, "no exec posture probe was made"
    assert all(r.url.path.startswith("/exec/") for r in exec_reqs), [
        r.url.path for r in exec_reqs
    ]
    # And never the CONTAINERS-gated path that a compliant proxy won't 403.
    assert not any(
        "/containers/" in r.url.path and r.url.path.endswith("/exec")
        for r in router.requests
    )


async def test_validate_flags_an_unrestricted_proxy_and_stops():
    # VOLUMES not blocked (200) ⇒ the proxy allowlist is not in force.
    router = _healthy_router()
    router.routes = [
        r if r[1] != "/volumes" else ("GET", "/volumes", httpx.Response(200, json=[]))
        for r in router.routes
    ]
    prov = DockerProvisioner(_cfg(), transport=router.transport(), tcp_probe=lambda h, p: _true())
    legs = await prov.validate()
    posture = next(leg for leg in legs if leg.name == "privilege_posture")
    assert posture.ok is False
    assert "NOT blocked" in posture.detail and "volumes" in posture.detail
    # It refuses to run a probe container through an unrestricted endpoint.
    assert [leg.name for leg in legs] == ["endpoint_reachable", "privilege_posture"]
    assert not router.saw("POST", "/images/create")


async def test_validate_scans_pull_stream_for_errors():
    router = _healthy_router()
    router.routes = [
        r if r[1] != "/images/create"
        else ("POST", "/images/create", httpx.Response(200, content=b'{"status":"Pulling"}\n{"error":"manifest unknown"}\n'))
        for r in router.routes
    ]
    prov = DockerProvisioner(_cfg(), transport=router.transport(), tcp_probe=lambda h, p: _true())
    legs = await prov.validate()
    pull = next(leg for leg in legs if leg.name == "image_pull")
    assert pull.ok is False and "manifest unknown" in pull.detail
    # No probe container attempted after a failed pull.
    assert not router.saw("POST", "/containers/create")


async def test_validate_reports_unreachable_public_host():
    router = _healthy_router()
    prov = DockerProvisioner(_cfg(), transport=router.transport(), tcp_probe=lambda h, p: _false())
    legs = await prov.validate()
    reach = next(leg for leg in legs if leg.name == "public_reachable")
    assert reach.ok is False and "NOT reachable" in reach.detail
    # Even on a failed dial, the probe container is still cleaned up.
    assert router.saw("DELETE", "/containers/probe1")


async def test_validate_passes_on_a_bridge_with_an_egress_advisory():
    # A normal bridge is REQUIRED for TCP (an internal network can't publish a
    # port). The leg passes but, under egress=deny, advises firewall rules — and
    # validation continues to the later legs (unlike a hard failure).
    router = _healthy_router()  # network is a bridge
    prov = DockerProvisioner(_cfg(), transport=router.transport(), tcp_probe=lambda h, p: _true())
    legs = await prov.validate()
    iso = next(leg for leg in legs if leg.name == "network_isolation")
    assert iso.ok is True and "firewall" in iso.detail
    # It did NOT stop early — image pull + probe run happened.
    assert router.saw("POST", "/images/create")


async def test_validate_warns_internal_network_wont_publish_ports():
    # An internal network denies egress but can't publish TCP ports — the leg
    # passes (existence) yet flags that published ports won't route.
    router = _healthy_router()
    router.routes = [
        r if r[1] != "/networks/flagpost-instances"
        else ("GET", "/networks/flagpost-instances", httpx.Response(200, json={"Internal": True}))
        for r in router.routes
    ]
    prov = DockerProvisioner(_cfg(), transport=router.transport(), tcp_probe=lambda h, p: _true())
    legs = await prov.validate()
    iso = next(leg for leg in legs if leg.name == "network_isolation")
    assert iso.ok is True and "will NOT route" in iso.detail


async def test_validate_fails_when_network_missing():
    router = _healthy_router()
    router.routes = [
        r if r[1] != "/networks/flagpost-instances"
        else ("GET", "/networks/flagpost-instances", httpx.Response(404, json={"message": "not found"}))
        for r in router.routes
    ]
    prov = DockerProvisioner(_cfg(), transport=router.transport(), tcp_probe=lambda h, p: _true())
    legs = await prov.validate()
    iso = next(leg for leg in legs if leg.name == "network_isolation")
    assert iso.ok is False and "does not exist" in iso.detail


async def test_validate_isolation_notes_egress_allowed():
    # An explicitly egress-allowed config: the bridge passes with no firewall
    # advisory.
    router = _healthy_router()
    prov = DockerProvisioner(
        _cfg(egress_denied=False),
        transport=router.transport(),
        tcp_probe=lambda h, p: _true(),
    )
    legs = await prov.validate()
    iso = next(leg for leg in legs if leg.name == "network_isolation")
    assert iso.ok is True and "egress allowed" in iso.detail


async def test_validate_rejects_truncated_pull_stream():
    # Stream ends with no error AND no terminal "Status:" marker ⇒ partial pull.
    router = _healthy_router()
    router.routes = [
        r if r[1] != "/images/create"
        else ("POST", "/images/create", httpx.Response(200, content=b'{"status":"Pulling fs layer"}\n{"status":"Downloading"}\n'))
        for r in router.routes
    ]
    prov = DockerProvisioner(_cfg(), transport=router.transport(), tcp_probe=lambda h, p: _true())
    legs = await prov.validate()
    pull = next(leg for leg in legs if leg.name == "image_pull")
    assert pull.ok is False and "truncated" in pull.detail
    assert not router.saw("POST", "/containers/create")


def test_probe_command_is_shell_free_execform_and_unprivileged():
    # The reachability probe must be exec-form argv (NO shell to inject into),
    # must not use nc's execute-on-connect (-e/-c, the classic RCE) or -k
    # (unsupported in busybox), and must bind an unprivileged port (CapDrop ALL
    # forbids <1024). See the security note in provisioner_docker.py.
    from utils.provisioner_docker import _DEFAULT_PROBE_CMD, _PROBE_PORT

    # Exec form: argv list, launched directly, not through a shell.
    assert isinstance(_DEFAULT_PROBE_CMD, list)
    assert _DEFAULT_PROBE_CMD[0] == "nc"
    assert "sh" not in _DEFAULT_PROBE_CMD and "-c" not in _DEFAULT_PROBE_CMD
    # No execute-on-connect and no unsupported keep-alive.
    for arg in _DEFAULT_PROBE_CMD:
        assert arg not in ("-e", "-c", "-k", "-lk", "-lke")
    # The only interpolated value is the constant port, as its own argv element.
    assert str(_PROBE_PORT) in _DEFAULT_PROBE_CMD
    assert _PROBE_PORT >= 1024


async def test_real_challenge_create_wraps_nothing_in_a_shell():
    # The invariant behind the nc concern: a REAL instance runs the author's
    # image entrypoint untouched — Flagpost never sets a Cmd for a real
    # challenge, so no author/competitor input is ever placed on a command line
    # or through a shell. The flag and env travel as structured Env entries
    # (execve environment), not interpolated into any command.
    router = (
        _Router()
        .on("POST", "/containers/create", httpx.Response(201, json={"Id": "x"}))
        .on("POST", "/start", httpx.Response(204))
    )
    prov = DockerProvisioner(_cfg(), transport=router.transport())
    await prov.create(
        _spec(
            env={"EVIL": "$(touch /pwned)", "SEMI": "a; rm -rf /"},
            flag_plaintext="flag{`id`}",
        )
    )
    body = router.create_body()
    # No command at all — the image's own entrypoint runs.
    assert "Cmd" not in body
    assert "Entrypoint" not in body
    # The shell-metacharacter env values are passed as inert structured Env,
    # never a shell string.
    assert "EVIL=$(touch /pwned)" in body["Env"]
    assert "FLAG=flag{`id`}" in body["Env"]


async def test_start_304_already_started_is_success():
    router = (
        _Router()
        .on("POST", "/containers/create", httpx.Response(201, json={"Id": "h304"}))
        .on("POST", "/start", httpx.Response(304))  # already started
    )
    prov = DockerProvisioner(_cfg(), transport=router.transport())
    assert await prov.create(_spec()) == "h304"


async def test_list_raises_on_daemon_error():
    # A 500 from the daemon must RAISE, never return [] — else the orphan reaper
    # would conclude nothing exists and skip cleanup.
    router = _Router().on("GET", "/containers/json", httpx.Response(500, json={"message": "boom"}))
    prov = DockerProvisioner(_cfg(), transport=router.transport())
    with pytest.raises(ProvisionerError, match="listing instances failed"):
        await prov.list()


async def test_tmpfs_and_ulimits_are_always_hardened():
    # Defense-in-depth fields the author cannot influence.
    router = (
        _Router()
        .on("POST", "/containers/create", httpx.Response(201, json={"Id": "x"}))
        .on("POST", "/start", httpx.Response(204))
    )
    prov = DockerProvisioner(_cfg(), transport=router.transport())
    await prov.create(_spec(env={"FLAG": "author-attempt"}, resource_limits={"cpu": 99}))
    hc = router.create_body()["HostConfig"]
    assert hc["Tmpfs"] == {"/tmp": "rw,noexec,nosuid,nodev,size=64m"}
    assert {"Name": "nofile", "Soft": 1024, "Hard": 1024} in hc["Ulimits"]
    # Author env for FLAG is respected here (static mode passes env through) but
    # the hardening fields are fixed regardless of resource_limit games.
    assert hc["CapDrop"] == ["ALL"] and hc["Privileged"] is False


async def test_validate_short_circuits_on_unreachable_endpoint():
    router = _Router()  # everything 500/unrouted; /_ping errors via transport
    def handler(request):
        raise httpx.ConnectError("connection refused")
    prov = DockerProvisioner(_cfg(), transport=httpx.MockTransport(handler), tcp_probe=lambda h, p: _true())
    legs = await prov.validate()
    assert [leg.name for leg in legs] == ["endpoint_reachable"]
    assert legs[0].ok is False and "failed" in legs[0].detail.lower()


# tiny awaitable helpers for the fake tcp_probe
async def _true() -> bool:
    return True


async def _false() -> bool:
    return False


# --- F1: registry credential is scoped to its own registry -------------------


def _reg_auth(server: str) -> str:
    """A base64 X-Registry-Auth blob (Docker AuthConfig) for ``server``."""
    return base64.b64encode(
        json.dumps({"username": "u", "password": "p", "serveraddress": server}).encode()
    ).decode()


def test_image_registry_host_follows_docker_rules():
    assert image_registry_host("ghcr.io/example/pwn:1") == "ghcr.io"
    assert image_registry_host("registry.example.com:5000/x") == "registry.example.com:5000"
    assert image_registry_host("localhost:5000/x") == "localhost:5000"
    # No dotted/colon'd first component -> Docker Hub.
    assert image_registry_host("alpine:3.20") == "docker.io"
    assert image_registry_host("library/alpine:3") == "docker.io"


def test_credential_registry_host_parses_serveraddress():
    assert credential_registry_host(_reg_auth("ghcr.io")) == "ghcr.io"
    assert credential_registry_host(_reg_auth("https://index.docker.io/v1/")) == "docker.io"
    assert credential_registry_host(None) is None
    assert credential_registry_host("not base64 at all !!!") is None


@pytest.mark.asyncio
async def test_registry_credential_is_never_forwarded_to_a_foreign_registry():
    # F1: image_ref is author-controlled (challenge_edit). The operator's
    # site-global registry credential must go ONLY to the registry it belongs to,
    # never to an attacker-named registry host in the image reference.
    router = _Router()
    cfg = _cfg(registry_auth=_reg_auth("ghcr.io"))
    prov = DockerProvisioner(cfg, transport=router.transport())

    await prov._pull_image("ghcr.io/example/pwn:1")     # matches -> credential sent
    await prov._pull_image("evil.attacker.com/x:latest")  # foreign -> credential withheld

    pulls = {
        r.url.params.get("fromImage"): r
        for r in router.requests
        if r.url.path.endswith("/images/create")
    }
    assert pulls["ghcr.io/example/pwn"].headers.get("X-Registry-Auth") == cfg.registry_auth
    assert "X-Registry-Auth" not in pulls["evil.attacker.com/x"].headers


# --- provision bounds (#456) -------------------------------------------------


class _TrickleStream(httpx.AsyncByteStream):
    """A pull that never finishes but never *stalls* either — a progress line
    every 50ms, forever. This is the case the per-read _TIMEOUT_PULL can't see:
    bytes keep flowing, so no read ever waits long enough to time out."""

    async def __aiter__(self):
        import asyncio

        while True:
            await asyncio.sleep(0.05)
            yield b'{"status":"Downloading","progress":"[=>   ]"}\n'


async def test_pull_has_a_total_budget_not_just_a_per_read_timeout(monkeypatch):
    import asyncio

    import utils.provisioner_docker as docker_mod

    monkeypatch.setattr(docker_mod, "_PULL_TOTAL", 0.3)
    router = _Router().on(
        "POST", "/images/create", httpx.Response(200, stream=_TrickleStream())
    )
    prov = DockerProvisioner(_cfg(), transport=router.transport())

    # Without the total bound this never returns; the outer wait_for turns a
    # regression into a failure instead of a hung suite.
    ok, detail = await asyncio.wait_for(
        prov._pull_image("ghcr.io/example/pwn:1"), timeout=5.0
    )
    assert ok is False
    assert "did not finish within" in detail, detail


async def test_cancelled_start_tears_down_the_created_container():
    """Between /containers/create returning and create() returning the handle,
    the container exists but the caller can't see it. A cancellation there (the
    provision ceiling, #456) used to leave it for the two-tick orphan GC."""
    import asyncio

    start_seen = asyncio.Event()

    async def _hang_on_start(request):
        start_seen.set()
        await asyncio.Event().wait()  # never returns

    router = (
        _Router()
        .on("POST", "/containers/create", httpx.Response(201, json={"Id": "c-half"}))
        .on("POST", "/containers/c-half/start", _hang_on_start)
        .on("DELETE", "/containers/c-half", httpx.Response(204))
    )
    prov = DockerProvisioner(_cfg(), transport=router.transport())

    task = asyncio.ensure_future(prov.create(_spec()))
    await asyncio.wait_for(start_seen.wait(), timeout=5.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert router.saw("DELETE", "/containers/c-half"), (
        "a cancelled start must tear down the container it already created"
    )
