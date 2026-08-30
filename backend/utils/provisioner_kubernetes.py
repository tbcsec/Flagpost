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
    extra_headers: dict[str, str] = field(default_factory=dict)


def _truncate(text: str) -> str:
    text = text.strip()
    return text if len(text) <= _MAX_ERROR_BODY else text[:_MAX_ERROR_BODY] + "…"


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

    # --- validate() — minimal here; the full staged run lands in slice 4 -----

    async def validate(self) -> list[CheckResult]:
        legs: list[CheckResult] = []
        # 1. API server reachable + authenticated.
        try:
            ver = await self._request("GET", "/version", timeout=_TIMEOUT_QUICK)
        except ProvisionerError as exc:
            legs.append(CheckResult("endpoint_reachable", False, str(exc)))
            return legs
        if ver.status_code == 401:
            legs.append(
                CheckResult(
                    "endpoint_reachable",
                    False,
                    "the API server rejected the service-account token (401)",
                )
            )
            return legs
        if ver.status_code != 200:
            legs.append(
                CheckResult(
                    "endpoint_reachable",
                    False,
                    f"GET /version returned {ver.status_code}: {_status_detail(ver)}",
                )
            )
            return legs
        git_version = ""
        try:
            git_version = ver.json().get("gitVersion", "")
        except ValueError:
            pass
        legs.append(
            CheckResult(
                "endpoint_reachable",
                True,
                f"API server reachable{f', {git_version}' if git_version else ''}",
            )
        )

        # 2. The namespace is operable by the token — list Deployments in it
        # (the right the Role grants; also proves the namespace exists).
        ns = await self._request(
            "GET", self._apps("deployments"), timeout=_TIMEOUT_QUICK
        )
        if ns.status_code == 200:
            legs.append(
                CheckResult(
                    "namespace_ready",
                    True,
                    f"namespace '{self._cfg.namespace}' is operable",
                )
            )
        else:
            legs.append(
                CheckResult(
                    "namespace_ready",
                    False,
                    f"cannot list Deployments in namespace "
                    f"'{self._cfg.namespace}': {_status_detail(ns)}",
                )
            )
        return legs
