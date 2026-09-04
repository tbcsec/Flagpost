# Threat model — challenge instancing

Challenge instancing (#266/#320, ADR-0036) is the one Flagpost subsystem that
**runs adversary-controlled, deliberately-vulnerable code**: a challenge author
ships an image designed to be exploited, and competitors exploit it. Every other
subsystem treats its inputs as data; here the *workload itself* is hostile. This
document states what we defend, how, and what stays the operator's job.

## Assets & trust boundaries

- **The control plane** — Postgres, Redis, MinIO, the API. An exploited instance
  reaching it is the worst case (data theft, tampering, pivot). It must be
  unreachable from the instance network.
- **Peer instances** — one team's exploited box must not reach another team's.
- **Cloud credentials** — the instance-metadata endpoint (`169.254.169.254`,
  IPv6 `fd00:ec2::254`) hands out IAM credentials; it must be unreachable.
- **The host / cluster** — an instance must not escalate to the node (container
  breakout) or hold any orchestrator credential.

The trust boundary is the **instance network / namespace**: everything inside is
hostile; everything the control plane runs is outside and must not be reachable
across it.

## What an instance is *given*

Nothing privileged, on either backend. The author supplies **only** an image
reference, ports, and non-secret env — never raw Docker options or raw pod
fields. Flagpost composes the entire runtime spec itself:

| Control | Docker | Kubernetes |
|---|---|---|
| Capabilities | `CapDrop: ["ALL"]` | `capabilities.drop: ["ALL"]` |
| Privilege escalation | `no-new-privileges` | `allowPrivilegeEscalation: false` |
| Root filesystem | `ReadonlyRootfs`, tmpfs `/tmp` | `readOnlyRootFilesystem`, emptyDir `/tmp` |
| Syscall filter | Docker default seccomp | `seccompProfile: RuntimeDefault` |
| Privileged mode | `Privileged: false` | `privileged: false` |
| Orchestrator credential | n/a (socket proxy) | `automountServiceAccountToken: false` |
| CPU / memory | `NanoCpus` / `Memory` | `resources.limits` (requests == limits) |
| PID / fd exhaustion | `PidsLimit` + `nofile` ulimit | **operator** (kubelet `--pod-max-pids`) |

The one gap is **per-pod PID/fd caps on Kubernetes**: there is no pod-spec field
for them (they are a kubelet/node setting), so they are an operator
responsibility on the challenge nodes, not something Flagpost can pin in the
manifest. cpu/memory limits still bound the memory-heavy case.

## How the control plane / peers / metadata are isolated

### Docker
Egress isolation is a **host-firewall** responsibility (ADR-0036 amendment): a
normal bridge network is required (an `internal` network can't publish TCP
ports, so it would break the whole feature), so the operator must drop forwarded
traffic from the instance subnet except the competitor-facing ports, and always
block `169.254.169.254`. The `network_isolation` Test-connection leg *reminds*
of this; it cannot verify firewall rules. The privilege-posture leg proves the
endpoint is a restricted socket **proxy**, never a raw `/var/run/docker.sock`
(the app can't hold host-root through a mounted socket).

The same firewall must drop **inter-instance** traffic on the bridge. Docker's
default `icc=true` lets any container on the shared bridge open a connection to
any other, so a competitor who exploits their own instance (the intended
pwn/web solve) can reach a neighbour's on the same bridge by IP:port — which
also sidesteps the unguessable-subdomain control on HTTP instances (GHSA-vgrr).
`icc=false` would block this but breaks the shared Caddy ingress, so peer
isolation on the docker backend is the operator's firewall rule (or a
per-challenge network), **not** the default bridge — unlike the kubernetes
backend, which enforces it in-cluster. Treat the shared bridge as a shared LAN.

### Kubernetes
Isolation is **enforced in-cluster** by a per-instance NetworkPolicy (the upgrade
over docker's documentation-only egress):

- **deny mode** (default) — egress is DNS-only; the internet, control plane,
  peers, and metadata IP are all blocked at once. Peer isolation is free: a pod
  that can't initiate any connection can't reach a neighbour. The DNS rule is
  scoped to the cluster DNS pods (`k8s-app=kube-dns` in `kube-system`), not any
  host on port 53 — otherwise "DNS-only" would itself be a full outbound channel
  (DNS tunnelling / a reverse shell to `attacker:53`) (GHSA-vgrr).
- **allow mode** — egress everywhere *except* the metadata IPs (both families)
  and, when `k8s_cluster_cidr` is configured, the cluster's pod/service ranges —
  so peers and the control plane stay unreachable even for an
  internet-legitimate challenge. A namespace **default-deny-egress baseline**
  (in `k8s/instances-rbac.yaml`) covers the startup window before a pod's own
  policy is programmed.

This all depends on a **policy-enforcing CNI**. Flannel *accepts* NetworkPolicy
objects but does not enforce them — so the `egress_enforcement` Test-connection
leg actively runs a deny-all pod and checks it is genuinely blocked (with a
no-policy positive control, so an air-gapped node can't produce a false pass).

## Residual risks (accepted / operator-owned)

- **A non-enforcing CNI** → no isolation. Caught by `egress_enforcement`; the
  operator must run Calico/Cilium/kube-router. *Detected, not prevented.*
- **`k8s_cluster_cidr` unset in allow mode** → peers/control plane reachable by
  IP for internet-enabled challenges. Recommended in the UI; documented here.
- **Docker inter-instance reachability** → the shared bridge does not isolate
  peers; the operator's host firewall must drop bridge-internal traffic (or run
  per-challenge networks). The kubernetes backend enforces this in-cluster; the
  docker backend does not (GHSA-vgrr). *Operator-owned.*
- **Kubernetes PID/fd exhaustion** → a fork bomb can pressure the node. Operator
  sets a kubelet `--pod-max-pids`. *(Docker pins this; k8s can't in-manifest.)*
- **The socket proxy / API can't inspect payloads** → isolation rests on the
  app-composed hardened spec plus the recommended **sacrificial challenge host**
  (a separate box/cluster from the control plane). Don't run instances on the
  same kernel/cluster as Postgres et al. for a high-risk event.
- **Container breakout (0-day)** → mitigated by the hardened spec + sacrificial
  host, not eliminated. Depth over a single wall.
- **Registry / image trust** → the image is author-supplied content; the pull
  credential is forwarded only to its scoped registry (never leaked to an
  attacker-named one). Authors are trusted staff (`challenge_edit`), not the
  public.

## Backup / export boundary

Deployment specs are portable authoring content and ride the backup + ctfcli
(validated on import, the #324 lesson). **Instances are runtime state and are
never exported.** Secrets — the registry credential, the k8s bearer token — live
on the site settings row, are encrypted at rest (ADR-0020), write-only over the
API, and dropped from every export. Nothing secret crosses the portability
boundary.
