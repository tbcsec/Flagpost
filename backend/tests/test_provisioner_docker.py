"""DockerProvisioner (#266, ADR-0036 §1) — unit-tested with a mocked httpx
transport and a fake TCP dialer, so the hardened create payload, the lifecycle
calls, and the whole staged validate() run are exercised without a real Docker
daemon (the utils/ai/client.py MockTransport pattern).

The create-body assertions are the security crux: every privileged field must
be pinned by Flagpost regardless of what a challenge author supplies.
"""

import json

import httpx
import pytest

from utils.provisioner_docker import (
    LABEL_MANAGED,
    DockerConfig,
    DockerProvisioner,
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
            return httpx.Response(500, json={"message": f"unrouted {request.method} {request.url.path}"})

        return httpx.MockTransport(handler)

    def create_body(self) -> dict:
        for r in self.requests:
            if r.method == "POST" and r.url.path.endswith("/containers/create"):
                return json.loads(r.content)
        raise AssertionError("no create request captured")

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
    # Exposure: attached to the isolated network, port published on bind_ip.
    assert hc["NetworkMode"] == "flagpost-instances"
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
        # the instance network exists and is internal (egress denied)
        .on("GET", "/networks/flagpost-instances", httpx.Response(200, json={"Internal": True}))
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


async def test_validate_fails_on_non_internal_network():
    # Network exists but is NOT internal ⇒ instances could reach the control
    # plane. The leg must fail and later legs must not run.
    router = _healthy_router()
    router.routes = [
        r if r[1] != "/networks/flagpost-instances"
        else ("GET", "/networks/flagpost-instances", httpx.Response(200, json={"Internal": False}))
        for r in router.routes
    ]
    prov = DockerProvisioner(_cfg(), transport=router.transport(), tcp_probe=lambda h, p: _true())
    legs = await prov.validate()
    iso = next(leg for leg in legs if leg.name == "network_isolation")
    assert iso.ok is False and "NOT internal" in iso.detail
    assert [leg.name for leg in legs] == ["endpoint_reachable", "privilege_posture", "network_isolation"]
    assert not router.saw("POST", "/images/create")


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


async def test_validate_skips_isolation_when_egress_allowed():
    # An explicitly egress-allowed config doesn't require an internal network.
    router = _healthy_router()
    prov = DockerProvisioner(
        _cfg(require_internal_network=False),
        transport=router.transport(),
        tcp_probe=lambda h, p: _true(),
    )
    legs = await prov.validate()
    iso = next(leg for leg in legs if leg.name == "network_isolation")
    assert iso.ok is True and "not required" in iso.detail


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
