"""The ``kubernetes`` provisioner kind (#320, ADR-0036 §1).

Speaks the Kubernetes REST API over httpx to a configured API server, exactly
as ``provisioner_docker`` speaks the Docker Engine API — same injectable
``httpx.AsyncBaseTransport`` seam (``httpx.MockTransport`` in tests), so the
hardened manifests and the whole lifecycle are exercised without a live
cluster. A new backend is a new kind, not a fork.

Authentication is a **ServiceAccount bearer token** with a **namespace-scoped
Role** (ADR-0036 §1, #320 D2): everything lives in one operator-configured
namespace, so the token never needs cluster-scoped rights (no namespace
creation, no cross-namespace reach). Flagpost composes every manifest itself —
drop-ALL capabilities, ``allowPrivilegeEscalation: false``, read-only rootfs,
``RuntimeDefault`` seccomp, no mounted API token — so a challenge author
supplies an image and ports, never raw pod fields.

Per instance, ``create`` lays down (all named ``flagpost-inst-<instance_id>``,
labelled ``flagpost.io/managed=true``):

- a **Deployment** (replicas=1) — the health-check + auto-restart substrate: a
  TCP ``livenessProbe`` restarts a hung container and ``restartPolicy`` +
  the ReplicaSet replace a crashed/evicted pod, entirely in-cluster (the
  Klodd/kCTF-equivalent the issue names);
- a **Service** — ``NodePort`` for TCP exposure (requesting the host port the
  lifecycle service already allocated from the shared range, so a docker
  published port and a k8s NodePort draw from one ledger), ``ClusterIP`` for
  HTTP;
- an **Ingress** (HTTP only) — host ``<subdomain>.<chal_base_domain>``,
  reusing the Phase 2 routing shape (#319); TLS is the ingress controller's
  wildcard cert, not per-ingress.

NetworkPolicy isolation (egress-deny, metadata-IP block) is composed in the
following slice; ``destroy`` already sweeps a NetworkPolicy so that slice only
adds the create side.
"""

from __future__ import annotations

import ipaddress
import logging
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

import httpx

from utils.provisioners import (
    CheckResult,
    ProvisionSpec,
    Provisioner,
    ProvisionerError,
    register_provisioner,
)

logger = logging.getLogger(__name__)

# Label keys stamped on every managed object. list() filters on MANAGED so the
# orphan reaper can never see an object Flagpost didn't create; the selector
# labels wire a Service/Deployment to its pods.
LABEL_MANAGED = "flagpost.io/managed"
LABEL_INSTANCE = "flagpost.io/instance-id"
LABEL_CHALLENGE = "flagpost.io/challenge-id"
LABEL_COMPETITION = "flagpost.io/competition-id"

# Bound outbound calls (hang-catchers, not budgets). The readiness wait has its
# own attempt budget below.
_TIMEOUT_QUICK = 10.0
_TIMEOUT_LIFECYCLE = 30.0

_MAX_ERROR_BODY = 500

# Cloud metadata service — always blocked from instance egress (the SSRF /
# credential-theft target every hardened runtime denies; ADR-0036 §amendment,
# #320 D5). A host address per family so only the metadata IP itself is excepted.
_METADATA_IP = "169.254.169.254/32"
_METADATA_IP6 = "fd00:ec2::254/128"  # IPv6 IMDS (dual-stack clouds)

# validate() probes (#320 D8). All run under the hardened spec, so the listener
# binds an UNPRIVILEGED port (caps dropped ⇒ no CAP_NET_BIND_SERVICE). Both
# commands are exec-form argv with NO shell and NO user-supplied input, so
# neither can become an injection sink; the listener has no `-e`/`-c`
# (execute-on-connect, the classic netcat RCE) — a single-shot `nc -l`.
_PROBE_PORT = 45000
_PROBE_LABEL = "flagpost.io/probe"
_PROBE_LISTEN_CMD = ["nc", "-l", "-p", str(_PROBE_PORT)]
# The egress-enforcement probe dials a RAW external IP (no DNS needed, so a
# deny-all egress policy — which also blocks DNS — still isolates the test): if
# it connects, the CNI is not enforcing the policy.
_EGRESS_PROBE_CMD = ["wget", "--timeout=4", "-q", "-O", "/dev/null", "http://1.1.1.1/"]
_PROBE_POLL_ATTEMPTS = 30
_PROBE_POLL_INTERVAL = 2.0

# Least-privilege posture matrix (#320 D8 leg 2), checked via
# SelfSubjectAccessReview. The namespace-scoped Role MUST grant the first set
# (or provisioning can't work) and MUST be denied the second (or the token is
# over-privileged — the k8s analogue of the docker socket-proxy's 403s; a
# cluster-admin token deliberately fails this leg). Tuples: (verb, group,
# resource, subresource).
_POSTURE_ALLOW = (
    ("create", "apps", "deployments", ""),
    ("delete", "apps", "deployments", ""),
    ("create", "", "services", ""),
    ("create", "networking.k8s.io", "networkpolicies", ""),
    ("create", "networking.k8s.io", "ingresses", ""),
    ("list", "", "pods", ""),
)
_POSTURE_DENY = (
    ("create", "", "pods", "exec"),   # running a command in a live instance
    ("get", "", "secrets", ""),       # reading cluster secrets
    ("create", "", "namespaces", ""),  # cluster-scoped
    ("list", "", "nodes", ""),         # cluster-scoped
)
# Resources whose SSAR is cluster-scoped (no namespace attribute).
_CLUSTER_SCOPED = {"namespaces", "nodes"}
_SSAR_PATH = "/apis/authorization.k8s.io/v1/selfsubjectaccessreviews"

# Readiness wait after the manifests are laid down: poll the Deployment until a
# replica is Ready, so a bad image (ErrImagePull) / crash-loop fails the
# provision cleanly with a reason rather than parking a never-serving "running"
# row — the docker kind gets this free (its create pulls first + start fails).
_READY_ATTEMPTS = 60
_READY_INTERVAL = 2.0


def _resource_name(instance_id: str) -> str:
    """The single name every per-instance object shares (Deployment / Service /
    Ingress / NetworkPolicy), so the row and its cluster objects map 1:1 and the
    orphan reaper can diff by name."""
    return f"flagpost-inst-{instance_id}"


@dataclass(frozen=True)
class KubernetesConfig:
    """Everything the kubernetes kind needs, derived from ``InstanceSettings``.
    Kept apart from the ORM model so the provisioner has no DB dependency and
    unit tests construct it directly (the ``DockerConfig`` split)."""

    # API server base URL, e.g. https://10.0.0.1:6443. A trusted operator
    # setting (the endpoint_url class), not run through the SSRF blocklist.
    endpoint_url: str
    # ServiceAccount bearer token (already whitespace-stripped at the settings
    # boundary). Presented as ``Authorization: Bearer``.
    token: str
    # Namespace every object lives in.
    namespace: str = "flagpost-instances"
    # Public node/LB host competitors dial for a NodePort (the connection
    # string endpoints() hands back), analogous to the docker public_host.
    public_host: str = ""
    # HTTP routing base domain (#319); an instance is reached at
    # ``https://<subdomain>.<chal_base_domain>`` through the ingress.
    chal_base_domain: str = ""
    # PEM CA bundle verifying the API server's serving cert; None = system trust.
    ca_cert: str | None = None
    # ``ingressClassName`` for per-instance Ingresses; None = cluster default.
    ingress_class: str | None = None
    # Name of an operator-created imagePullSecret in the namespace (private
    # images); None = public only.
    image_pull_secret: str | None = None
    # Comma-separated pod/service CIDRs excepted from NetworkPolicy (slice 3).
    cluster_cidr: str | None = None
    # True when the site egress policy is ``deny`` (drives NetworkPolicy, slice 3).
    egress_denied: bool = True
    default_cpu: float = 1.0
    default_memory_mb: int = 256
    # Image the validate() probes run (busybox: nc listener + wget). Overridable
    # per install for an air-gapped registry; mirrors DockerConfig.probe_image.
    probe_image: str = "alpine:3.20"
    extra_headers: dict[str, str] = field(default_factory=dict)


def _truncate(text: str) -> str:
    text = text.strip()
    return text if len(text) <= _MAX_ERROR_BODY else text[:_MAX_ERROR_BODY] + "…"


def _json_or_none(resp: httpx.Response) -> dict | None:
    """Parse a JSON body, or None if it isn't JSON — so a broken intermediary
    proxy returning a non-JSON 200 degrades a validate() leg to a clean fail
    rather than raising a ValueError that 500s the Test-connection route."""
    try:
        body = resp.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _status_detail(resp: httpx.Response) -> str:
    """Human detail from a Kubernetes error — the apiserver returns a
    ``{"kind":"Status","message":...,"reason":...}`` object on failure."""
    try:
        body = resp.json()
        if isinstance(body, dict):
            msg = body.get("message")
            if isinstance(msg, str) and msg:
                return _truncate(msg)
    except (ValueError, AttributeError):
        pass
    return _truncate(resp.text) or f"HTTP {resp.status_code}"


@register_provisioner
class KubernetesProvisioner(Provisioner):
    kind: ClassVar[str] = "kubernetes"

    def __init__(
        self,
        config: KubernetesConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        tcp_probe: Callable[[str, int], Awaitable[bool]] | None = None,
        http_probe: Callable[[str], Awaitable[tuple[bool, str]]] | None = None,
        ready_attempts: int = _READY_ATTEMPTS,
    ) -> None:
        self._cfg = config
        self._transport = transport
        self._ready_attempts = ready_attempts
        if sleep is not None:
            self._sleep = sleep
        else:
            import asyncio

            self._sleep = asyncio.sleep
        # The two non-API-server actions the staged validate() needs — a raw TCP
        # dial to the public NodePort, and the wildcard-DNS/ingress probe — are
        # injectable seams, so the whole validate() run is unit-testable against
        # a mock transport (the docker kind's pattern). Reused from the docker
        # provisioner, which owns the canonical implementations.
        from utils.provisioner_docker import _http_ingress_probe, _tcp_dial

        self._dial = tcp_probe or _tcp_dial
        self._http_ingress = http_probe or _http_ingress_probe
        # Build the TLS verify context once. A PEM CA string can't go straight
        # to httpx's ``verify=``; it needs an SSLContext. None → system trust.
        # Ignored entirely when a transport is injected (tests).
        self._verify: bool | ssl.SSLContext = True
        if config.ca_cert:
            try:
                self._verify = ssl.create_default_context(cadata=config.ca_cert)
            except ssl.SSLError:
                # A malformed CA is caught at the settings boundary; if one still
                # reaches here, fail closed to system trust rather than crash.
                logger.warning("kubernetes CA cert did not parse; using system trust")

    # --- HTTP plumbing -------------------------------------------------------

    def _client(self, timeout: float) -> httpx.AsyncClient:
        headers = {
            "Authorization": f"Bearer {self._cfg.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            **(self._cfg.extra_headers or {}),
        }
        return httpx.AsyncClient(
            base_url=self._cfg.endpoint_url,
            timeout=timeout,
            transport=self._transport,
            headers=headers,
            verify=self._verify,
        )

    async def _request(
        self, method: str, path: str, *, timeout: float, **kwargs: Any
    ) -> httpx.Response:
        async with self._client(timeout) as http:
            try:
                return await http.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                raise ProvisionerError(
                    f"request to the Kubernetes API failed: {exc}"
                ) from exc

    # --- API path helpers ----------------------------------------------------

    def _apps(self, plural: str) -> str:
        return f"/apis/apps/v1/namespaces/{self._cfg.namespace}/{plural}"

    def _core(self, plural: str) -> str:
        return f"/api/v1/namespaces/{self._cfg.namespace}/{plural}"

    def _net(self, plural: str) -> str:
        return f"/apis/networking.k8s.io/v1/namespaces/{self._cfg.namespace}/{plural}"

    # --- manifest composition ------------------------------------------------

    def _labels(self, spec: ProvisionSpec) -> dict[str, str]:
        return {
            LABEL_MANAGED: "true",
            LABEL_INSTANCE: spec.instance_id,
            LABEL_CHALLENGE: spec.challenge_id,
            LABEL_COMPETITION: spec.competition_id,
        }

    def _pod_template(self, spec: ProvisionSpec) -> dict[str, Any]:
        """The hardened pod template (#320 D6). Every privileged field is pinned
        by Flagpost, never author-controlled — the k8s analogue of the docker
        HostConfig hardening, plus the k8s-only pins (RuntimeDefault seccomp,
        no auto-mounted API token, no service-env injection).

        One docker backstop has NO in-manifest k8s equivalent: a per-pod **PID
        cap** (docker's ``PidsLimit``) and **fd cap** (its ``nofile`` ulimit),
        the fork-bomb / fd-exhaustion containment. Kubernetes expresses these
        only via the kubelet (``--pod-max-pids``) or node config, not a pod-spec
        field, so they are an **operator responsibility** on the challenge nodes
        — called out in the deploy guide + threat model (slice 7), not silently
        assumed. cpu/memory limits below still bound the memory-heavy case."""
        limits = spec.resource_limits or {}
        cpu = float(limits.get("cpu", self._cfg.default_cpu))
        memory_mb = int(limits.get("memory_mb", self._cfg.default_memory_mb))

        env = dict(spec.env)
        if spec.flag_plaintext is not None:
            # Injected only in memory, never persisted (ADR-0036 §3).
            env[spec.flag_env] = spec.flag_plaintext
        env_list = [{"name": k, "value": v} for k, v in env.items()]

        resources = {
            # requests == limits: no burst, predictable scheduling, hard ceiling.
            "requests": {"cpu": f"{cpu}", "memory": f"{memory_mb}Mi"},
            "limits": {"cpu": f"{cpu}", "memory": f"{memory_mb}Mi"},
        }

        container: dict[str, Any] = {
            "name": "challenge",
            "image": spec.image_ref,
            "env": env_list,
            "resources": resources,
            "securityContext": {
                "allowPrivilegeEscalation": False,
                "privileged": False,
                "readOnlyRootFilesystem": True,
                "capabilities": {"drop": ["ALL"]},
            },
            # A small writable scratch dir so the read-only rootfs doesn't break
            # well-behaved challenges (the docker Tmpfs /tmp analogue).
            "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
        }
        if spec.ports:
            container["ports"] = [{"containerPort": p} for p in spec.ports]
            # In-cluster health check → auto-restart: a TCP probe on the primary
            # port restarts a hung container (kubelet), the Deployment replaces a
            # crashed one. No platform polling.
            container["livenessProbe"] = {
                "tcpSocket": {"port": spec.ports[0]},
                "initialDelaySeconds": 10,
                "periodSeconds": 15,
                "failureThreshold": 3,
            }

        pod_spec: dict[str, Any] = {
            "containers": [container],
            "restartPolicy": "Always",  # required for a Deployment pod
            # A challenge pod must never hold an API credential, and must not get
            # the cluster's service host/port env vars leaked in.
            "automountServiceAccountToken": False,
            "enableServiceLinks": False,
            "securityContext": {"seccompProfile": {"type": "RuntimeDefault"}},
            "volumes": [{"name": "tmp", "emptyDir": {"sizeLimit": "64Mi"}}],
        }
        if self._cfg.image_pull_secret:
            pod_spec["imagePullSecrets"] = [{"name": self._cfg.image_pull_secret}]

        return {
            "metadata": {"labels": self._labels(spec)},
            "spec": pod_spec,
        }

    def _deployment_body(self, spec: ProvisionSpec) -> dict[str, Any]:
        name = _resource_name(spec.instance_id)
        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": name,
                "namespace": self._cfg.namespace,
                "labels": self._labels(spec),
            },
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {LABEL_INSTANCE: spec.instance_id}},
                "template": self._pod_template(spec),
            },
        }

    def _service_body(self, spec: ProvisionSpec) -> dict[str, Any]:
        name = _resource_name(spec.instance_id)
        base = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": name,
                "namespace": self._cfg.namespace,
                "labels": self._labels(spec),
            },
        }
        if spec.exposure == "http":
            # ClusterIP behind the Ingress; the first declared port is the
            # upstream (default 80, matching the docker http path).
            http_port = spec.ports[0] if spec.ports else 80
            base["spec"] = {
                "type": "ClusterIP",
                "selector": {LABEL_INSTANCE: spec.instance_id},
                "ports": [
                    {"port": http_port, "targetPort": http_port, "protocol": "TCP"}
                ],
            }
            return base
        # TCP: NodePort requesting the exact host port the lifecycle service
        # allocated from the shared range, so endpoints() reads back the same
        # port and the used-port ledger stays authoritative (#320 D4). k8s
        # rejecting the port (out of its NodePort range / taken) is a clean
        # create failure, surfaced with detail.
        ports = []
        for container_port, host_port in spec.host_ports.items():
            ports.append(
                {
                    # k8s requires a unique name on every ServicePort once a
                    # Service declares more than one; harmless on a single port.
                    "name": f"p-{container_port}",
                    "port": container_port,
                    "targetPort": container_port,
                    "nodePort": host_port,
                    "protocol": "TCP",
                }
            )
        base["spec"] = {
            "type": "NodePort",
            "selector": {LABEL_INSTANCE: spec.instance_id},
            "ports": ports,
        }
        return base

    def _partition_cidrs(self) -> tuple[list[str], list[str]]:
        """The configured cluster CIDRs split by address family (v4, v6). k8s
        requires every ipBlock ``except`` to be the SAME family as its ``cidr``
        and contained within it, so a mixed dual-stack ``k8s_cluster_cidr`` must
        be spread across a ``0.0.0.0/0`` and a ``::/0`` block — not crammed into
        one, which the apiserver rejects."""
        v4: list[str] = []
        v6: list[str] = []
        if not self._cfg.cluster_cidr:
            return v4, v6
        for part in self._cfg.cluster_cidr.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                (v6 if ipaddress.ip_network(part, strict=False).version == 6 else v4).append(part)
            except ValueError:
                continue  # the settings validator already normalised these
        return v4, v6

    def _egress_rules(self) -> list[dict[str, Any]]:
        """Egress half of the per-instance NetworkPolicy (#320 D5) — the
        load-bearing isolation control. DNS is always allowed (a pod needs it to
        resolve anything, and kube-dns lives in the cluster range that ``allow``
        mode otherwise excepts, so it is carved back in explicitly)."""
        dns = {"ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]}
        if self._cfg.egress_denied:
            # Deny mode (default): DNS only. Blocks the internet, the control
            # plane, peer instances and the metadata IP in one stroke — and
            # peer isolation falls out for free (a pod that can't initiate any
            # connection can't reach a neighbour).
            return [dns]
        # Allow mode: everything EXCEPT the cloud metadata IP and — when the
        # operator has configured the cluster's pod/service ranges — those
        # ranges, so peers and the control plane stay unreachable even for an
        # internet-enabled challenge. A block per address family so dual-stack
        # clusters are covered (an IPv6 except under an IPv4 cidr is rejected by
        # the apiserver) and the IPv6 half isn't silently left wide open.
        # Without cluster_cidr set, peers are reachable in allow mode (documented
        # residual risk, threat model).
        v4_except, v6_except = self._partition_cidrs()
        return [
            dns,
            {
                "to": [
                    {"ipBlock": {"cidr": "0.0.0.0/0", "except": [_METADATA_IP, *v4_except]}},
                    {"ipBlock": {"cidr": "::/0", "except": [_METADATA_IP6, *v6_except]}},
                ]
            },
        ]

    def _ingress_rules(self, spec: ProvisionSpec) -> list[dict[str, Any]]:
        """Ingress half (#320 D5): allow the declared container ports from any
        source, so both a NodePort's DNAT'd traffic AND the in-cluster HTTP
        ingress controller reach the pod. Peer isolation is delivered by the
        egress rules (a peer can't initiate to us), NOT by restricting ingress
        source here — excepting the cluster range on ingress would block the
        ingress controller (which lives in it) and break HTTP challenges. An
        exposure=none pod publishes nothing, so it gets an empty ingress list =
        deny-all-in."""
        if not spec.ports:
            return []
        return [{"ports": [{"protocol": "TCP", "port": p} for p in spec.ports]}]

    def _networkpolicy_body(self, spec: ProvisionSpec) -> dict[str, Any]:
        return {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {
                "name": _resource_name(spec.instance_id),
                "namespace": self._cfg.namespace,
                "labels": self._labels(spec),
            },
            "spec": {
                "podSelector": {"matchLabels": {LABEL_INSTANCE: spec.instance_id}},
                "policyTypes": ["Ingress", "Egress"],
                "ingress": self._ingress_rules(spec),
                "egress": self._egress_rules(),
            },
        }

    def _ingress_body(self, spec: ProvisionSpec) -> dict[str, Any]:
        if not spec.subdomain or not self._cfg.chal_base_domain:
            raise ProvisionerError(
                "HTTP instance is missing its subdomain or base domain"
            )
        name = _resource_name(spec.instance_id)
        http_port = spec.ports[0] if spec.ports else 80
        fqdn = f"{spec.subdomain}.{self._cfg.chal_base_domain}"
        spec_body: dict[str, Any] = {
            "rules": [
                {
                    "host": fqdn,
                    "http": {
                        "paths": [
                            {
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {
                                        "name": name,
                                        "port": {"number": http_port},
                                    }
                                },
                            }
                        ]
                    },
                }
            ]
        }
        if self._cfg.ingress_class:
            spec_body["ingressClassName"] = self._cfg.ingress_class
        return {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {
                "name": name,
                "namespace": self._cfg.namespace,
                "labels": self._labels(spec),
            },
            "spec": spec_body,
        }

    # --- lifecycle -----------------------------------------------------------

    async def create(self, spec: ProvisionSpec) -> str:
        if not spec.image_ref:
            raise ProvisionerError("kubernetes deployment has no image reference")
        name = _resource_name(spec.instance_id)

        # An exposure="none" instance publishes no endpoint (a unique-flag holder
        # or bot-visited pod), so it gets a Deployment ONLY — no Service (a
        # zero-port Service is invalid) and no Ingress. The docker kind's
        # NetworkMode "none" analogue; network isolation for it comes from the
        # NetworkPolicy in the following slice.
        needs_service = spec.exposure in ("tcp", "http")

        # Lay down NetworkPolicy → Deployment → (Service) → (Ingress). Any
        # failure — a bad create, a transient error mid-way, or a never-ready pod
        # — tears down whatever already landed via _safe_delete (total +
        # 404-tolerant), so a failed provision never leaks objects. Everything is
        # inside the try, so even a Deployment-create failure sweeps the
        # NetworkPolicy that preceded it.
        try:
            # Isolate the pod (egress-deny / peer + metadata block) BEFORE the
            # Deployment object exists, so a policy-enforcing CNI programs
            # egress-deny before the container can start emitting — every
            # instance gets a NetworkPolicy, including exposure=none (#320 D5).
            # (The CNI applies policy eventually-consistently, so a namespace
            # default-deny baseline — shipped with the slice-7 bootstrap — is what
            # fully closes the startup window; this ordering minimises it. On a
            # CNI that doesn't enforce policy at all the object is accepted-but-
            # inert, which the slice-4 validate() egress leg detects.)
            netpol = await self._request(
                "POST", self._net("networkpolicies"),
                json=self._networkpolicy_body(spec), timeout=_TIMEOUT_LIFECYCLE,
            )
            if netpol.status_code not in (200, 201):
                raise ProvisionerError(
                    f"network policy create failed: {_status_detail(netpol)}"
                )

            dep = await self._request(
                "POST", self._apps("deployments"),
                json=self._deployment_body(spec), timeout=_TIMEOUT_LIFECYCLE,
            )
            if dep.status_code not in (200, 201):
                raise ProvisionerError(
                    f"deployment create failed: {_status_detail(dep)}"
                )

            if needs_service:
                svc = await self._request(
                    "POST", self._core("services"),
                    json=self._service_body(spec), timeout=_TIMEOUT_LIFECYCLE,
                )
                if svc.status_code not in (200, 201):
                    raise ProvisionerError(
                        f"service create failed: {_status_detail(svc)}"
                    )

            if spec.exposure == "http":
                ing = await self._request(
                    "POST", self._net("ingresses"),
                    json=self._ingress_body(spec), timeout=_TIMEOUT_LIFECYCLE,
                )
                if ing.status_code not in (200, 201):
                    raise ProvisionerError(
                        f"ingress create failed: {_status_detail(ing)}"
                    )

            # Wait for a Ready replica so a bad image / crash-loop fails the
            # provision with a reason instead of parking a never-serving row.
            await self._await_ready(name, spec)
        except Exception:
            # Guarantee the create() contract: on ANY post-Deployment failure —
            # a create error, a transient blip in the readiness poll, or a
            # never-ready timeout — clean up every object that landed. Without
            # this, a transient poll error would escape leaving the Deployment
            # (+Service/+Ingress) orphaned until the reaper's GC.
            await self._safe_delete(name)
            raise
        return name

    async def _await_ready(self, name: str, spec: ProvisionSpec) -> None:
        """Poll the Deployment until a replica is Ready. A transient API error on
        a single poll is absorbed (keep polling); a genuinely never-ready pod
        exhausts the budget and raises with its failure reason. The caller
        (create) cleans up on any raise, so this never needs to itself."""
        for _ in range(self._ready_attempts):
            try:
                resp = await self._request(
                    "GET",
                    f"{self._apps('deployments')}/{name}",
                    timeout=_TIMEOUT_QUICK,
                )
            except ProvisionerError:
                # A blip talking to the API server — not evidence the pod failed.
                await self._sleep(_READY_INTERVAL)
                continue
            if resp.status_code == 200:
                status = resp.json().get("status") or {}
                if int(status.get("readyReplicas") or 0) >= 1:
                    return
            await self._sleep(_READY_INTERVAL)
        # Budget exhausted: surface why (ErrImagePull / CrashLoopBackOff).
        detail = await self._pod_failure_detail(spec.instance_id)
        raise ProvisionerError(f"instance did not become ready: {detail}")

    async def _pod_failure_detail(self, instance_id: str) -> str:
        """Best-effort waiting/terminated reason from the instance's pod(s), so
        a stuck provision names its cause (image pull, crash) instead of a bare
        timeout."""
        try:
            resp = await self._request(
                "GET",
                self._core("pods"),
                params={"labelSelector": f"{LABEL_INSTANCE}={instance_id}"},
                timeout=_TIMEOUT_QUICK,
            )
            if resp.status_code != 200:
                return "readiness timed out (pod status unavailable)"
            for pod in resp.json().get("items") or []:
                statuses = (pod.get("status") or {}).get("containerStatuses") or []
                for cs in statuses:
                    state = cs.get("state") or {}
                    waiting = state.get("waiting") or {}
                    terminated = state.get("terminated") or {}
                    reason = waiting.get("reason") or terminated.get("reason")
                    if reason:
                        msg = waiting.get("message") or terminated.get("message") or ""
                        return _truncate(f"{reason}: {msg}" if msg else reason)
        except ProvisionerError:
            pass
        return "readiness timed out"

    async def status(self, handle: str) -> str:
        resp = await self._request(
            "GET", f"{self._apps('deployments')}/{handle}", timeout=_TIMEOUT_QUICK
        )
        if resp.status_code == 404:
            return "unknown"
        if resp.status_code != 200:
            return "unknown"
        status = resp.json().get("status") or {}
        return "running" if int(status.get("readyReplicas") or 0) >= 1 else "stopped"

    async def endpoints(self, handle: str) -> list[dict[str, Any]]:
        resp = await self._request(
            "GET", f"{self._core('services')}/{handle}", timeout=_TIMEOUT_QUICK
        )
        if resp.status_code != 200:
            return []
        spec = resp.json().get("spec") or {}
        # ClusterIP (http) has no reachable node port — the planned
        # ``https://<subdomain>.<base>`` URL on the row stands (the docker http
        # posture). Only a NodePort yields a tcp connection string here.
        if spec.get("type") != "NodePort":
            return []
        out: list[dict[str, Any]] = []
        for port in spec.get("ports") or []:
            node_port = port.get("nodePort")
            if node_port:
                out.append(
                    {"kind": "tcp", "host": self._cfg.public_host, "port": int(node_port)}
                )
        return out

    async def destroy(self, handle: str) -> None:
        await self._delete_all(handle, raise_on_error=True)

    async def _safe_delete(self, name: str) -> None:
        # Best-effort cleanup of a partially-created / abandoned instance. A
        # persistent failure leaves a real orphan for the reaper, so it is
        # LOGGED, not swallowed (the caller is usually already raising).
        try:
            await self._delete_all(name, raise_on_error=False)
        except ProvisionerError as exc:
            logger.warning(
                "kubernetes cleanup of %s failed, leaving a possible orphan: %s",
                name,
                exc,
            )

    async def _delete_all(self, name: str, *, raise_on_error: bool) -> None:
        """Delete every per-instance object by its shared name. Idempotent: a
        404 is a no-op (already gone / never created — e.g. the NetworkPolicy an
        exposure=none instance never had). Must be idempotent per the contract
        (the reaper retries)."""
        targets = [
            f"{self._apps('deployments')}/{name}",
            f"{self._core('services')}/{name}",
            # Always attempt the NetworkPolicy (slice-3 create side) + Ingress —
            # a 404 when they don't exist is harmless and keeps destroy total.
            f"{self._net('networkpolicies')}/{name}",
            f"{self._net('ingresses')}/{name}",
        ]
        first_error: str | None = None
        for path in targets:
            resp = await self._request(
                "DELETE", path,
                params={"propagationPolicy": "Foreground"}, timeout=_TIMEOUT_LIFECYCLE,
            )
            # 200 = deleted, 202 = accepted (background), 404 = already gone.
            if resp.status_code not in (200, 202, 404) and first_error is None:
                first_error = f"{path}: {_status_detail(resp)}"
        if first_error and raise_on_error:
            raise ProvisionerError(f"instance teardown failed: {first_error}")

    async def list(self) -> list[str]:
        resp = await self._request(
            "GET",
            self._apps("deployments"),
            params={"labelSelector": f"{LABEL_MANAGED}=true"},
            timeout=_TIMEOUT_QUICK,
        )
        if resp.status_code != 200:
            raise ProvisionerError(
                f"listing instances failed: {_status_detail(resp)}"
            )
        return [
            item["metadata"]["name"]
            for item in resp.json().get("items") or []
            if item.get("metadata", {}).get("name")
        ]

    # --- validate() — the staged "Test connection" (ADR-0036 §1, #320 D8) ----

    async def validate(self) -> list[CheckResult]:
        legs: list[CheckResult] = []

        # 1. API server reachable + the token is accepted.
        try:
            ver = await self._request("GET", "/version", timeout=_TIMEOUT_QUICK)
        except ProvisionerError as exc:
            legs.append(CheckResult("endpoint_reachable", False, str(exc)))
            return legs
        if ver.status_code == 401:
            legs.append(CheckResult(
                "endpoint_reachable", False,
                "the API server rejected the service-account token (401)",
            ))
            return legs
        if ver.status_code != 200:
            legs.append(CheckResult(
                "endpoint_reachable", False,
                f"GET /version returned {ver.status_code}: {_status_detail(ver)}",
            ))
            return legs
        git_version = ""
        try:
            git_version = ver.json().get("gitVersion", "")
        except ValueError:
            pass
        legs.append(CheckResult(
            "endpoint_reachable", True,
            f"API server reachable{f', {git_version}' if git_version else ''}",
        ))

        # 2. Least-privilege posture — the security-critical leg. The token must
        # hold exactly the namespaced rights it needs and be denied the
        # dangerous ones (a cluster-admin token fails here, deliberately).
        posture = await self._check_posture()
        legs.append(posture)
        if not posture.ok:
            # Don't drive probe pods through a wrongly-scoped token.
            return legs

        # 3. The namespace exists + is operable (lists Deployments in it).
        ns = await self._request("GET", self._apps("deployments"), timeout=_TIMEOUT_QUICK)
        if ns.status_code == 200:
            legs.append(CheckResult(
                "namespace_ready", True, f"namespace '{self._cfg.namespace}' is operable",
            ))
        else:
            legs.append(CheckResult(
                "namespace_ready", False,
                f"cannot list Deployments in namespace '{self._cfg.namespace}': "
                f"{_status_detail(ns)}",
            ))
            return legs

        # 4. NetworkPolicy objects are accepted by the API.
        legs.append(await self._check_netpol_support())

        # 5. The honest leg: does the CNI actually ENFORCE NetworkPolicy? A
        # deny-all-egress pod that still reaches the internet means policies are
        # accepted-but-inert — instances would not be isolated. ~20-30s.
        legs.append(await self._check_egress_enforcement())

        # 6. Run a hardened probe pod behind a NodePort and dial the public host
        # end-to-end — the closed-firewall / wrong-public-host catcher.
        legs.extend(await self._check_probe_run_and_dial())

        # 7. HTTP mode (#319): wildcard DNS resolves + the ingress answers. Only
        # when a base domain is configured; reuses the docker kind's probe.
        if self._cfg.chal_base_domain:
            probe_fqdn = f"http-probe.{self._cfg.chal_base_domain}"
            ok, detail = await self._http_ingress(probe_fqdn)
            legs.append(CheckResult("http_ingress", ok, detail))
        return legs

    async def _ssar(
        self, verb: str, group: str, resource: str, *, namespaced: bool = True, subresource: str = ""
    ) -> tuple[bool | None, str]:
        """One SelfSubjectAccessReview: ``(allowed, detail)``; allowed is None on
        an API/transport error (the caller treats that as a failed posture)."""
        attrs: dict[str, Any] = {"verb": verb, "group": group, "resource": resource}
        if namespaced:
            attrs["namespace"] = self._cfg.namespace
        if subresource:
            attrs["subresource"] = subresource
        body = {
            "apiVersion": "authorization.k8s.io/v1",
            "kind": "SelfSubjectAccessReview",
            "spec": {"resourceAttributes": attrs},
        }
        try:
            resp = await self._request("POST", _SSAR_PATH, json=body, timeout=_TIMEOUT_QUICK)
        except ProvisionerError as exc:
            return None, str(exc)
        if resp.status_code not in (200, 201):
            return None, _status_detail(resp)
        data = _json_or_none(resp)
        if data is None:
            return None, "the API returned a non-JSON response to the access review"
        return bool((data.get("status") or {}).get("allowed")), ""

    async def _check_posture(self) -> CheckResult:
        ok = True
        notes: list[str] = []
        for verb, group, resource, sub in _POSTURE_ALLOW:
            allowed, detail = await self._ssar(verb, group, resource, subresource=sub)
            label = f"{verb} {resource}" + (f"/{sub}" if sub else "")
            if allowed is None:
                ok = False
                notes.append(f"{label}: review errored ({detail})")
            elif allowed:
                notes.append(f"{label}: allowed ✓")
            else:
                ok = False
                notes.append(f"{label}: DENIED — the namespace Role is missing this right")
        for verb, group, resource, sub in _POSTURE_DENY:
            namespaced = resource not in _CLUSTER_SCOPED
            allowed, detail = await self._ssar(
                verb, group, resource, namespaced=namespaced, subresource=sub
            )
            label = f"{verb} {resource}" + (f"/{sub}" if sub else "")
            if allowed is None:
                ok = False
                notes.append(f"{label}: review errored ({detail})")
            elif not allowed:
                notes.append(f"{label}: blocked ✓")
            else:
                ok = False
                notes.append(
                    f"{label}: NOT blocked — the token is over-privileged; a "
                    "namespace-scoped Role must not grant this"
                )
        return CheckResult("privilege_posture", ok, "; ".join(notes))

    async def _delete_quietly(self, path: str) -> None:
        try:
            await self._request("DELETE", path, timeout=_TIMEOUT_QUICK)
        except ProvisionerError:
            pass

    async def _check_netpol_support(self) -> CheckResult:
        name = "flagpost-netpol-probe"
        # Clear any leftover so the probe create can't 409.
        await self._delete_quietly(f"{self._net('networkpolicies')}/{name}")
        body = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": name, "namespace": self._cfg.namespace,
                         "labels": {LABEL_MANAGED: "true"}},
            "spec": {
                "podSelector": {"matchLabels": {_PROBE_LABEL: "netpol-probe"}},
                "policyTypes": ["Egress"],
                "egress": [],
            },
        }
        try:
            resp = await self._request(
                "POST", self._net("networkpolicies"), json=body, timeout=_TIMEOUT_QUICK
            )
        except ProvisionerError as exc:
            return CheckResult("network_policy_support", False, str(exc))
        if resp.status_code in (200, 201):
            await self._delete_quietly(f"{self._net('networkpolicies')}/{name}")
            return CheckResult("network_policy_support", True, "NetworkPolicy objects are accepted")
        return CheckResult(
            "network_policy_support", False,
            f"cannot create a NetworkPolicy: {_status_detail(resp)}",
        )

    def _probe_pod_body(
        self, name: str, command: list[str], *, ports: list[int] | None = None
    ) -> dict[str, Any]:
        container: dict[str, Any] = {
            "name": "probe",
            "image": self._cfg.probe_image,
            "command": command,
            "securityContext": {
                "allowPrivilegeEscalation": False,
                "privileged": False,
                "readOnlyRootFilesystem": True,
                "capabilities": {"drop": ["ALL"]},
            },
            "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
        }
        if ports:
            container["ports"] = [{"containerPort": p} for p in ports]
        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": name,
                "namespace": self._cfg.namespace,
                "labels": {LABEL_MANAGED: "true", _PROBE_LABEL: name},
            },
            "spec": {
                "containers": [container],
                "restartPolicy": "Never",
                "automountServiceAccountToken": False,
                "enableServiceLinks": False,
                "securityContext": {"seccompProfile": {"type": "RuntimeDefault"}},
                "volumes": [{"name": "tmp", "emptyDir": {"sizeLimit": "16Mi"}}],
            },
        }

    async def _await_pod(
        self, name: str, want: tuple[str, ...]
    ) -> tuple[str | None, int | None]:
        """Poll a probe Pod until its phase is in ``want``. Returns
        ``(phase, exit_code)`` — exit_code from the terminated container when
        available, else None. A transient poll error is absorbed."""
        for _ in range(_PROBE_POLL_ATTEMPTS):
            try:
                resp = await self._request(
                    "GET", f"{self._core('pods')}/{name}", timeout=_TIMEOUT_QUICK
                )
            except ProvisionerError:
                await self._sleep(_PROBE_POLL_INTERVAL)
                continue
            if resp.status_code == 200:
                status = resp.json().get("status") or {}
                phase = status.get("phase")
                if phase in want:
                    exit_code = None
                    for cs in status.get("containerStatuses") or []:
                        term = (cs.get("state") or {}).get("terminated") or {}
                        if "exitCode" in term:
                            exit_code = int(term["exitCode"])
                    return phase, exit_code
            await self._sleep(_PROBE_POLL_INTERVAL)
        return None, None

    async def _run_egress_probe(
        self, name: str, *, with_policy: bool
    ) -> tuple[str | None, int | None, str | None]:
        """Run one raw-IP egress probe pod (optionally behind a deny-all-egress
        policy) and return ``(phase, exit_code, create_error)``. Pre-deletes any
        leftover of the same fixed name first (a hard-killed / concurrent prior
        run would otherwise 409), and always cleans up."""
        np_path = f"{self._net('networkpolicies')}/{name}"
        pod_path = f"{self._core('pods')}/{name}"
        await self._delete_quietly(pod_path)
        if with_policy:
            await self._delete_quietly(np_path)
        try:
            if with_policy:
                netpol = {
                    "apiVersion": "networking.k8s.io/v1",
                    "kind": "NetworkPolicy",
                    "metadata": {"name": name, "namespace": self._cfg.namespace,
                                 "labels": {LABEL_MANAGED: "true"}},
                    "spec": {
                        "podSelector": {"matchLabels": {_PROBE_LABEL: name}},
                        "policyTypes": ["Egress"],
                        "egress": [],  # deny ALL egress — the probe uses a raw IP
                    },
                }
                np = await self._request(
                    "POST", self._net("networkpolicies"), json=netpol, timeout=_TIMEOUT_QUICK
                )
                if np.status_code not in (200, 201):
                    return None, None, f"could not create the probe policy: {_status_detail(np)}"
            p = await self._request(
                "POST", self._core("pods"),
                json=self._probe_pod_body(name, _EGRESS_PROBE_CMD),
                timeout=_TIMEOUT_LIFECYCLE,
            )
            if p.status_code not in (200, 201):
                return None, None, f"could not create the probe pod: {_status_detail(p)}"
            phase, exit_code = await self._await_pod(name, ("Succeeded", "Failed"))
            return phase, exit_code, None
        finally:
            await self._delete_quietly(pod_path)
            if with_policy:
                await self._delete_quietly(np_path)

    async def _check_egress_enforcement(self) -> CheckResult:
        # Phase 1: does a deny-all-egress pod get blocked? exit 0 ⇒ it REACHED
        # the internet despite the policy ⇒ the CNI is not enforcing.
        phase, code, err = await self._run_egress_probe(
            "flagpost-egress-probe", with_policy=True
        )
        if err:
            return CheckResult("egress_enforcement", False, err)
        if phase is None or code is None:
            # Terminal-but-unreadable (evicted / OOM / status race) or a timeout:
            # the probe never actually tested egress — do NOT claim enforcement.
            return CheckResult(
                "egress_enforcement", False,
                "the egress probe did not report a result — could not confirm "
                "the CNI enforces NetworkPolicy; re-run Test connection",
            )
        if code == 0:
            return CheckResult(
                "egress_enforcement", False,
                "a deny-all-egress pod REACHED the internet — your CNI is not "
                "enforcing NetworkPolicy, so instances would not be isolated. "
                "Install a policy-enforcing CNI (Calico / Cilium) on the "
                "challenge nodes.",
            )
        # Phase 2 (positive control): it was blocked — but was that the POLICY,
        # or does this node simply have no route to the probe target (air-gapped
        # / egress-firewalled)? Re-run WITHOUT a policy; it must now reach, else
        # the enforcement question is unanswerable here rather than a pass.
        b_phase, b_code, b_err = await self._run_egress_probe(
            "flagpost-egress-baseline", with_policy=False
        )
        if b_err or b_phase is None or b_code is None or b_code != 0:
            return CheckResult(
                "egress_enforcement", False,
                "inconclusive: a probe pod could not reach the internet even "
                "WITHOUT a policy, so this node has no egress to the test target "
                "and enforcement can't be measured here — verify your CNI "
                "enforces NetworkPolicy another way",
            )
        return CheckResult(
            "egress_enforcement", True,
            "a deny-all-egress pod was blocked while an unrestricted one reached "
            "out — the CNI enforces NetworkPolicy",
        )

    async def _check_probe_run_and_dial(self) -> list[CheckResult]:
        legs: list[CheckResult] = []
        pod = "flagpost-probe"
        pod_path = f"{self._core('pods')}/{pod}"
        svc_path = f"{self._core('services')}/{pod}"
        # Clear any leftover of the fixed name from a hard-killed / concurrent
        # prior run so create() can't 409.
        await self._delete_quietly(pod_path)
        await self._delete_quietly(svc_path)
        pod_body = self._probe_pod_body(pod, _PROBE_LISTEN_CMD, ports=[_PROBE_PORT])
        svc_body = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": pod, "namespace": self._cfg.namespace,
                         "labels": {LABEL_MANAGED: "true"}},
            "spec": {
                "type": "NodePort",
                "selector": {_PROBE_LABEL: pod},
                # No nodePort ⇒ the apiserver auto-assigns one from its range.
                "ports": [{"name": "probe", "port": _PROBE_PORT,
                           "targetPort": _PROBE_PORT, "protocol": "TCP"}],
            },
        }
        try:
            p = await self._request(
                "POST", self._core("pods"), json=pod_body, timeout=_TIMEOUT_LIFECYCLE
            )
            if p.status_code not in (200, 201):
                legs.append(CheckResult("probe_run", False, f"create failed: {_status_detail(p)}"))
                return legs
            s = await self._request(
                "POST", self._core("services"), json=svc_body, timeout=_TIMEOUT_LIFECYCLE
            )
            if s.status_code not in (200, 201):
                legs.append(CheckResult("probe_run", False, f"service create failed: {_status_detail(s)}"))
                return legs
            phase, _ = await self._await_pod(pod, ("Running", "Succeeded", "Failed"))
            if phase not in ("Running", "Succeeded"):
                legs.append(CheckResult(
                    "probe_run", False,
                    "the probe pod did not start — check the probe image and node capacity",
                ))
                return legs
            legs.append(CheckResult("probe_run", True, "probe pod ran hardened"))

            # Read the auto-assigned NodePort and dial the public host.
            svc = await self._request("GET", svc_path, timeout=_TIMEOUT_QUICK)
            node_port = None
            if svc.status_code == 200:
                data = _json_or_none(svc) or {}
                ports = (data.get("spec") or {}).get("ports") or []
                node_port = ports[0].get("nodePort") if ports else None
            if not node_port:
                legs.append(CheckResult(
                    "public_reachable", False,
                    "no NodePort was assigned — check the Service NodePort range",
                ))
                return legs
            reachable = await self._dial(self._cfg.public_host, int(node_port))
            legs.append(CheckResult(
                "public_reachable", reachable,
                f"{self._cfg.public_host}:{node_port} "
                + ("reachable" if reachable else
                   "NOT reachable — firewall closed or public host wrong"),
            ))
        finally:
            await self._delete_quietly(svc_path)
            await self._delete_quietly(pod_path)
        return legs
