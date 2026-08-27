"""The ``docker`` provisioner kind (#266, ADR-0036 §1).

Talks the Docker Engine HTTP API over httpx to a configured endpoint that is
**always** a least-privilege socket proxy (tecnativa/docker-socket-proxy or
equivalent), never a raw ``/var/run/docker.sock`` mount. Flagpost composes the
entire container-create payload itself — hardened, with no field derived from
untrusted input beyond the image reference and the declared ports — so a
challenge author supplies an image and ports, never raw Docker options.

Testability mirrors utils/ai/client.py: every request goes through an
injectable ``httpx.AsyncBaseTransport`` (``httpx.MockTransport`` in tests), and
the one non-HTTP action — the public-reachability TCP dial — is an injectable
async callable. So the whole of ``validate()`` (leg ordering, the
privilege-posture 403 assertions, the streaming-pull error scan, reachability)
is exercised without a real Docker daemon.

Field names, status codes and the socket-proxy 403 behaviour are per the
Docker Engine API v1.47 spec and the proxy README (see ADR-0036 and the PR).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

import httpx

logger = logging.getLogger(__name__)

from utils.provisioners import (
    CheckResult,
    ProvisionSpec,
    Provisioner,
    ProvisionerError,
    register_provisioner,
)

# Every container Flagpost creates carries this label = "true". list() filters
# on it, so the orphan reaper can NEVER see, let alone destroy, a container the
# platform didn't create.
LABEL_MANAGED = "io.flagpost.managed"
LABEL_INSTANCE = "io.flagpost.instance_id"
LABEL_CHALLENGE = "io.flagpost.challenge_id"
LABEL_COMPETITION = "io.flagpost.competition_id"

# Bound outbound calls. Pulls are slow (a fresh image over the network); the
# rest are local proxy round-trips. These are hang-catchers, not budgets.
_TIMEOUT_QUICK = 10.0
_TIMEOUT_LIFECYCLE = 60.0
_TIMEOUT_PULL = 300.0

_MAX_ERROR_BODY = 500

# A tiny public image for the run/destroy + reachability validate legs. Chosen
# to be near-universally cached and cheap to pull; overridable per install.
_DEFAULT_PROBE_IMAGE = "alpine:3.20"

# Container port the probe listens on. An UNPRIVILEGED port: the hardened spec
# drops all caps and forbids privilege escalation, so binding <1024 inside the
# container would fail (no CAP_NET_BIND_SERVICE).
_PROBE_PORT = 45000

# Probe listener command for the reachability leg. Deliberately **exec-form
# argv, never `sh -c`**: there is no shell to parse it and nothing is
# string-interpolated, so this can never become a shell-injection sink even if a
# future change makes the port configurable. It also avoids `nc`'s dangerous
# modes entirely — NO `-e`/`-c` (execute-on-connect, the classic netcat RCE) and
# NO `-k` (unsupported in busybox anyway). A single-shot `nc -l -p PORT`: the one
# reachability dial connects, nc relays nothing (its stdin is the container's
# empty stdin, no `-e` to run anything), the dial closes, nc exits, the
# AutoRemove container is gone. Overridable per install for non-busybox images.
_DEFAULT_PROBE_CMD = ["nc", "-l", "-p", str(_PROBE_PORT)]


async def _tcp_dial(host: str, port: int, timeout: float = 5.0) -> bool:
    """Real public-reachability probe: open a TCP connection and close it.

    Injected as a seam so validate() is testable without a live listener.
    """
    import asyncio

    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except (OSError, asyncio.TimeoutError):
        return False


@dataclass(frozen=True)
class DockerConfig:
    """Everything the docker kind needs, derived from ``InstanceSettings`` plus
    a deployment's overrides. Kept apart from the settings model so the
    provisioner has no ORM dependency (and unit tests construct it directly)."""

    endpoint_url: str
    # Public hostname competitors connect to — replaces the container's bind IP
    # in the connection string endpoints() hands back. A trusted OPERATOR
    # setting (the SMTP-host / OIDC-issuer / endpoint_url class), so it is
    # deliberately NOT run through the ADR-0013 SSRF blocklist when the
    # reachability leg dials it: a challenge host legitimately lives on a
    # private/loopback address in the common same-host and private-subnet
    # topologies (ADR-0036 §1), which a blocklist would reject.
    public_host: str
    # Isolated bridge network the container is attached to. MUST be created with
    # ``internal: true`` at deploy time to deny egress and control-plane reach
    # (ADR-0036 §5). The provisioner references it by name AND — when egress is
    # denied — the ``network_isolation`` validate leg verifies its ``Internal``
    # flag, so a misconfigured (non-internal) network fails Test Connection
    # rather than silently letting instances reach Postgres/Redis/MinIO.
    network: str = "flagpost-instances"
    # When true (site egress policy = deny), validate() requires the network to
    # be internal. Set false only for an explicitly egress-allowed competition.
    require_internal_network: bool = True
    # Host interface published ports bind to. A challenge port must be reachable
    # by competitors — that's the feature — so 0.0.0.0 by default; isolation is
    # at the container (dropped caps, no-new-privileges, isolated net), not by
    # hiding the port.
    bind_ip: str = "0.0.0.0"
    default_cpu: float = 1.0
    default_memory_mb: int = 256
    default_pids: int = 256
    # Value for the ``X-Registry-Auth`` header (base64 JSON), or None for a
    # public registry.
    registry_auth: str | None = None
    probe_image: str = _DEFAULT_PROBE_IMAGE
    # Listener command for the reachability probe (busybox-safe default).
    probe_cmd: list[str] = field(default_factory=lambda: list(_DEFAULT_PROBE_CMD))
    # Extra Content-Type-less headers if a proxy needs them (rarely).
    extra_headers: dict[str, str] = field(default_factory=dict)


def _truncate(text: str) -> str:
    text = text.strip()
    return text if len(text) <= _MAX_ERROR_BODY else text[:_MAX_ERROR_BODY] + "…"


def _daemon_detail(resp: httpx.Response) -> str:
    """Best-effort human detail from a Docker error response — daemon errors
    are JSON ``{"message": ...}``; proxy 403s are HTML, so fall back to text."""
    try:
        msg = resp.json().get("message")
        if isinstance(msg, str) and msg:
            return _truncate(msg)
    except (ValueError, AttributeError):
        pass
    return _truncate(resp.text) or f"HTTP {resp.status_code}"


@register_provisioner
class DockerProvisioner(Provisioner):
    kind: ClassVar[str] = "docker"

    def __init__(
        self,
        config: DockerConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        tcp_probe: Callable[[str, int], Awaitable[bool]] | None = None,
    ) -> None:
        self._cfg = config
        self._transport = transport
        self._dial = tcp_probe or _tcp_dial

    # --- HTTP plumbing -------------------------------------------------------

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._cfg.endpoint_url,
            timeout=timeout,
            transport=self._transport,
            headers=self._cfg.extra_headers or None,
        )

    async def _request(
        self, method: str, path: str, *, timeout: float, **kwargs: Any
    ) -> httpx.Response:
        async with self._client(timeout) as http:
            try:
                return await http.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                raise ProvisionerError(
                    f"request to the container runtime failed: {exc}"
                ) from exc

    # --- lifecycle -----------------------------------------------------------

    def _container_body(self, spec: ProvisionSpec) -> dict[str, Any]:
        """Compose the hardened ``POST /containers/create`` payload. Every
        privileged field is pinned by Flagpost, not the author (ADR-0036 §1)."""
        limits = spec.resource_limits or {}
        cpu = float(limits.get("cpu", self._cfg.default_cpu))
        memory_mb = int(limits.get("memory_mb", self._cfg.default_memory_mb))
        pids = int(limits.get("pids", self._cfg.default_pids))

        env = dict(spec.env)
        if spec.flag_plaintext is not None:
            # Injected only in memory, never persisted (ADR-0036 §3).
            env[spec.flag_env] = spec.flag_plaintext
        env_list = [f"{k}={v}" for k, v in env.items()]

        host_config: dict[str, Any] = {
            # Hardening — fixed, never author-controlled.
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Privileged": False,
            "ReadonlyRootfs": True,
            "PidsLimit": pids,
            "Memory": memory_mb * 1024 * 1024,
            "NanoCpus": int(cpu * 1_000_000_000),
            "RestartPolicy": {"Name": "no"},
            "AutoRemove": True,
            "Binds": [],
            "Mounts": [],
            # A small writable scratch dir so ReadonlyRootfs doesn't break
            # well-behaved challenges that need /tmp. nodev too: no device nodes.
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=64m"},
            # File-descriptor ceiling — a cheap fd-exhaustion backstop on top of
            # PidsLimit (fork bombs) and Memory. Author cannot raise it.
            "Ulimits": [{"Name": "nofile", "Soft": 1024, "Hard": 1024}],
        }

        exposed: dict[str, dict] = {}
        if spec.exposure == "none" or not spec.host_ports:
            # No published port ⇒ no netns to publish into: full isolation.
            host_config["NetworkMode"] = "none"
        else:
            host_config["NetworkMode"] = self._cfg.network
            bindings: dict[str, list[dict[str, str]]] = {}
            for container_port, host_port in spec.host_ports.items():
                key = f"{container_port}/tcp"
                exposed[key] = {}
                bindings[key] = [
                    {"HostIp": self._cfg.bind_ip, "HostPort": str(host_port)}
                ]
            host_config["PortBindings"] = bindings

        body: dict[str, Any] = {
            "Image": spec.image_ref,
            "Env": env_list,
            "Labels": {
                LABEL_MANAGED: "true",
                LABEL_INSTANCE: spec.instance_id,
                LABEL_CHALLENGE: spec.challenge_id,
                LABEL_COMPETITION: spec.competition_id,
            },
            "HostConfig": host_config,
        }
        if exposed:
            body["ExposedPorts"] = exposed
        return body

    async def create(self, spec: ProvisionSpec) -> str:
        if not spec.image_ref:
            raise ProvisionerError("docker deployment has no image reference")

        # Ensure the image is present — the daemon's /containers/create 404s on
        # an absent image, so provision would otherwise fail for any image not
        # already cached on the instance host.
        pulled, detail = await self._pull_image(spec.image_ref)
        if not pulled:
            raise ProvisionerError(f"image pull failed: {detail}")

        name = f"flagpost-inst-{spec.instance_id}"
        created = await self._request(
            "POST",
            "/containers/create",
            params={"name": name},
            json=self._container_body(spec),
            timeout=_TIMEOUT_LIFECYCLE,
        )
        if created.status_code != 201:
            raise ProvisionerError(
                f"container create failed: {_daemon_detail(created)}"
            )
        handle = created.json()["Id"]

        started = await self._request(
            "POST", f"/containers/{handle}/start", timeout=_TIMEOUT_LIFECYCLE
        )
        # 204 = started; 304 = already started (idempotent). Anything else is a
        # failure — tear down the created-but-not-running container so a failed
        # provision never leaks.
        if started.status_code not in (204, 304):
            detail = _daemon_detail(started)
            await self._safe_destroy(handle)
            raise ProvisionerError(f"container start failed: {detail}")
        return handle

    async def status(self, handle: str) -> str:
        resp = await self._request(
            "GET", f"/containers/{handle}/json", timeout=_TIMEOUT_QUICK
        )
        if resp.status_code == 404:
            return "unknown"
        if resp.status_code != 200:
            return "unknown"
        state = resp.json().get("State") or {}
        return "running" if state.get("Running") else "stopped"

    async def endpoints(self, handle: str) -> list[dict[str, Any]]:
        resp = await self._request(
            "GET", f"/containers/{handle}/json", timeout=_TIMEOUT_QUICK
        )
        if resp.status_code != 200:
            return []
        ports = ((resp.json().get("NetworkSettings") or {}).get("Ports")) or {}
        out: list[dict[str, Any]] = []
        for port_key, bindings in ports.items():
            for binding in bindings or []:
                host_port = binding.get("HostPort")
                if host_port:
                    out.append(
                        {
                            "kind": "tcp",
                            "host": self._cfg.public_host,
                            "port": int(host_port),
                        }
                    )
        return out

    async def _safe_destroy(self, handle: str) -> None:
        # destroy() already treats 404 as a no-op; a *persistent* failure here
        # (500/permission/disk) leaves a real orphan the reaper must catch, so
        # it is LOGGED rather than silently swallowed — the caller is usually
        # already raising a different error and can't act on this one.
        try:
            await self.destroy(handle)
        except ProvisionerError as exc:
            logger.warning(
                "instance cleanup failed, leaving a possible orphan (%s): %s",
                handle,
                exc,
            )

    async def destroy(self, handle: str) -> None:
        resp = await self._request(
            "DELETE",
            f"/containers/{handle}",
            params={"force": "1"},
            timeout=_TIMEOUT_LIFECYCLE,
        )
        # 204 = removed. 404 = already gone (AutoRemove race / double reap) —
        # idempotent no-op, not an error (the contract requires this).
        if resp.status_code in (204, 404):
            return
        raise ProvisionerError(f"container remove failed: {_daemon_detail(resp)}")

    async def list(self) -> list[str]:
        resp = await self._request(
            "GET",
            "/containers/json",
            params={
                "all": "1",
                "filters": json.dumps({"label": [f"{LABEL_MANAGED}=true"]}),
            },
            timeout=_TIMEOUT_QUICK,
        )
        if resp.status_code != 200:
            raise ProvisionerError(
                f"listing instances failed: {_daemon_detail(resp)}"
            )
        return [c["Id"] for c in resp.json()]

    # --- validate() — the staged "Test connection" (ADR-0036 §1) -------------

    async def validate(self) -> list[CheckResult]:
        legs: list[CheckResult] = []

        # 1. Reachable + API version.
        try:
            ping = await self._request("GET", "/_ping", timeout=_TIMEOUT_QUICK)
        except ProvisionerError as exc:
            legs.append(CheckResult("endpoint_reachable", False, str(exc)))
            return legs  # nothing else can run
        if ping.status_code != 200:
            legs.append(
                CheckResult(
                    "endpoint_reachable",
                    False,
                    f"GET /_ping returned {ping.status_code}: {_daemon_detail(ping)}",
                )
            )
            return legs
        api_version = ping.headers.get("Api-Version", "unknown")
        legs.append(
            CheckResult(
                "endpoint_reachable",
                True,
                f"proxy reachable, Docker API version {api_version}",
            )
        )

        # 2. Privilege posture — the security-critical leg. The proxy must
        # return 403 for dangerous verbs; anything else means its allowlist is
        # NOT in force and the endpoint is effectively a raw socket.
        #
        # The exec probe targets ``/exec/<id>/start``, NOT ``/containers/<id>/
        # exec``: the socket proxy gates the latter under CONTAINERS (which we
        # *require* for create/start/inspect), so it forwards it to the daemon
        # regardless — verified against tecnativa/docker-socket-proxy. The
        # danger — running a command inside a live instance — is neutralised by
        # blocking exec *start*, which the proxy's own EXEC flag governs and
        # returns 403 for when off. Probing the container path instead reported a
        # false posture failure on a correctly-restricted proxy.
        posture_ok = True
        posture_notes: list[str] = []
        for label, method, path in (
            ("exec", "POST", "/exec/flagpost-probe/start"),
            ("volumes", "GET", "/volumes"),
            ("build", "POST", "/build"),
        ):
            try:
                r = await self._request(method, path, timeout=_TIMEOUT_QUICK)
            except ProvisionerError as exc:
                posture_ok = False
                posture_notes.append(f"{label}: probe errored ({exc})")
                continue
            if r.status_code == 403:
                posture_notes.append(f"{label}: blocked (403) ✓")
            else:
                posture_ok = False
                posture_notes.append(
                    f"{label}: NOT blocked — {method} {path} returned "
                    f"{r.status_code}, expected 403; the socket proxy is not "
                    "restricting dangerous verbs"
                )
        legs.append(
            CheckResult("privilege_posture", posture_ok, "; ".join(posture_notes))
        )
        if not posture_ok:
            # Refuse to go further: running a probe container through an
            # unrestricted endpoint is exactly what we must not encourage.
            return legs

        # 2b. Network isolation — verify the instance network is `internal`, so
        # instances can't reach the control plane (Postgres/Redis/MinIO/API) or
        # the internet, when the site egress policy is deny. Turns a deployment
        # assumption into a checked, testable precondition.
        iso_leg = await self._check_network_isolation()
        legs.append(iso_leg)
        if not iso_leg.ok:
            return legs

        # 3. Pull the probe image — drain the NDJSON stream and scan for an
        # in-stream error (a failed pull still opens with HTTP 200).
        pull_ok, pull_detail = await self._probe_pull()
        legs.append(CheckResult("image_pull", pull_ok, pull_detail))
        if not pull_ok:
            return legs

        # 4 + 5. Run a probe container that publishes a port, dial the public
        # host end-to-end, then tear it down. This is the leg that catches the
        # closed-firewall / wrong-public-host class before event day.
        legs.extend(await self._probe_run_and_dial())
        return legs

    async def _check_network_isolation(self) -> CheckResult:
        if not self._cfg.require_internal_network:
            return CheckResult(
                "network_isolation",
                True,
                "egress is allowed for this configuration — isolation not required",
            )
        try:
            resp = await self._request(
                "GET", f"/networks/{self._cfg.network}", timeout=_TIMEOUT_QUICK
            )
        except ProvisionerError as exc:
            return CheckResult("network_isolation", False, str(exc))
        if resp.status_code == 404:
            return CheckResult(
                "network_isolation",
                False,
                f"network '{self._cfg.network}' does not exist — create it with "
                "internal: true before enabling instances",
            )
        if resp.status_code != 200:
            return CheckResult(
                "network_isolation", False, _daemon_detail(resp)
            )
        internal = bool(resp.json().get("Internal"))
        if not internal:
            return CheckResult(
                "network_isolation",
                False,
                f"network '{self._cfg.network}' is NOT internal — instances could "
                "reach the control plane (Postgres/Redis/MinIO) or the internet; "
                "recreate it with internal: true",
            )
        return CheckResult(
            "network_isolation",
            True,
            f"network '{self._cfg.network}' is internal (egress denied)",
        )

    async def _probe_pull(self) -> tuple[bool, str]:
        return await self._pull_image(self._cfg.probe_image)

    async def _pull_image(self, image: str) -> tuple[bool, str]:
        """Pull ``image`` through the proxy, draining the NDJSON stream and
        requiring the terminal completion marker (not merely the absence of an
        error). Used by the validate probe AND by ``create`` — ``/containers/
        create`` 404s on an absent image and a challenge image is rarely
        pre-cached on the instance host; a present image is a fast no-op."""
        name, _, tag = image.partition(":")
        headers = (
            {"X-Registry-Auth": self._cfg.registry_auth}
            if self._cfg.registry_auth
            else {}
        )
        async with self._client(_TIMEOUT_PULL) as http:
            try:
                async with http.stream(
                    "POST",
                    "/images/create",
                    params={"fromImage": name, "tag": tag or "latest"},
                    headers=headers,
                ) as resp:
                    if resp.status_code != 200:
                        await resp.aread()
                        return False, (
                            f"pull of {image} failed: {_daemon_detail(resp)}"
                        )
                    # A pull opens with 200 then streams NDJSON; a mid-stream
                    # error, OR a stream that just ends early (connection reset
                    # after a partial layer), both mean the image is not ready.
                    # So require the terminal success marker — Docker closes a
                    # good pull with a "Status: Downloaded…" / "…up to date" line
                    # (or a Digest line) — not merely the absence of an error.
                    saw_terminal = False
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except ValueError:
                            continue
                        if obj.get("error"):
                            return False, (
                                f"pull of {image} errored: "
                                f"{_truncate(str(obj['error']))}"
                            )
                        status = str(obj.get("status", ""))
                        if status.startswith("Status:") or "Digest:" in status:
                            saw_terminal = True
            except httpx.HTTPError as exc:
                return False, f"pull of {image} failed: {exc}"
        if not saw_terminal:
            return False, (
                f"pull of {image} ended without a completion marker — the "
                "stream was truncated (partial download)"
            )
        return True, f"pulled {image}"

    async def _probe_run_and_dial(self) -> list[CheckResult]:
        legs: list[CheckResult] = []
        # A probe that listens on an UNPRIVILEGED port (the hardened spec drops
        # CAP_NET_BIND_SERVICE, so <1024 can't be bound).
        spec = ProvisionSpec(
            instance_id="probe",
            deployment_id="probe",
            challenge_id="probe",
            competition_id="probe",
            image_ref=self._cfg.probe_image,
            manifest=None,
            exposure="tcp",
            ports=[_PROBE_PORT],
            env={},
            resource_limits={"cpu": 0.5, "memory_mb": 64, "pids": 32},
            lifetime_s=60,
            subject_key="probe",
            # Let the daemon pick a free host port for the probe (HostPort "0").
            host_ports={_PROBE_PORT: 0},
        )
        # Run the busybox-safe listener so the reachability dial has a real
        # accept on the other end.
        body = self._container_body(spec)
        body["Cmd"] = self._cfg.probe_cmd

        created = await self._request(
            "POST", "/containers/create",
            params={"name": "flagpost-probe"}, json=body, timeout=_TIMEOUT_LIFECYCLE,
        )
        if created.status_code != 201:
            legs.append(
                CheckResult("probe_run", False, f"create failed: {_daemon_detail(created)}")
            )
            return legs
        handle = created.json()["Id"]
        try:
            started = await self._request(
                "POST", f"/containers/{handle}/start", timeout=_TIMEOUT_LIFECYCLE
            )
            if started.status_code not in (204, 304):
                legs.append(
                    CheckResult("probe_run", False, f"start failed: {_daemon_detail(started)}")
                )
                return legs
            legs.append(CheckResult("probe_run", True, "probe container ran and was hardened"))

            # Read the daemon-assigned host port, then dial the public host.
            eps = await self.endpoints(handle)
            if not eps:
                legs.append(
                    CheckResult(
                        "public_reachable",
                        False,
                        "probe published no port — check the port range and network config",
                    )
                )
                return legs
            port = eps[0]["port"]
            reachable = await self._dial(self._cfg.public_host, port)
            legs.append(
                CheckResult(
                    "public_reachable",
                    reachable,
                    f"{self._cfg.public_host}:{port} "
                    + ("reachable" if reachable else
                       "NOT reachable — firewall closed or public host wrong"),
                )
            )
        finally:
            await self._safe_destroy(handle)
        return legs
