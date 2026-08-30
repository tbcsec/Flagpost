# ADR-0036: Challenge instancing — provisioner contract, lifecycle, and flag semantics

**Status:** Accepted (amended 2026-08-27 — see "Amendment: egress model")
**Date:** 2026-08-27
**Architecture reference:** `ARCHITECTURE.md` §3 (events), §5 (automation), §7
(RBAC), §11 (modules). The instancing section itself is added to
`ARCHITECTURE.md` with the Phase 1 implementation, per #266.

## Context

Flagpost's challenge model is static: flags, attachments, hints,
prerequisites, scheduled release. There is no way to give each team (or each
user, in individual mode) an isolated, running copy of a challenge with live
connection details — which is table stakes for pwn, web, cloud and OT events,
and the hard blocker named in #266. The ecosystem solves this with
orchestration bolted onto the platform (CTFd-Whale and kin) or beside it
(rCTF + Klodd, kCTF on GKE).

Bringing this into Flagpost forces five decisions at once, and they are
entangled enough to record together:

1. **How deployment backends plug in** — one hardcoded Docker path, or an
   abstraction that can also cover Kubernetes and shared/static endpoints?
2. **Where slow container work runs** — the backend is single-process by
   default (ADR-0025/0026 made multi-worker opt-in); container starts take
   seconds and must not live on the request path. Does reaping justify a new
   worker process?
3. **What holding Docker privileges means** — the platform hosts deliberately
   vulnerable containers; the control plane must not be reachable from them,
   and the app must not hold host-root via a mounted Docker socket.
4. **How per-instance unique flags interact with grading**, first blood and
   dynamic-scoring decay.
5. **How competitors reach instances** — TCP and HTTP exposure, including
   when the instance host is a different machine from the platform.

A cross-cutting constraint from the owner: same-host and remote-host
deployment must be **as close to identical as possible**, configured in the
UI, with the out-of-band infrastructure work reduced to a bootstrap command —
and misconfiguration must surface as labelled, actionable errors in the admin
UI rather than as dead connection strings on event day.

## Decision

Ship instancing as an optional **`instances` module** (the seventh optional
module) built around a **provisioner kind registry**, with provisioning on
the existing background lane, reaping on the existing scheduler, hash-at-rest
unique flags resolved ahead of the static grading paths, TCP port-range
exposure first, and Docker access exclusively through a least-privilege
socket proxy whose health is proven by a **staged `validate()` contract**
surfaced in the UI as "Test connection". In detail:

### 1. Provisioner contract — kinds, like identity providers

A `Provisioner` is an async interface — `create(spec, subject) → handle`,
`status(handle)`, `endpoints(handle)`, `destroy(handle)`, `list()`,
`validate() → [CheckResult]` — registered by kind, exactly as external auth
registers `IdentityProvider` kinds (ADR-0021/0022/0033): **a new backend is a
new kind, not a fork**. Initial kinds:

- **`docker`** — talks the Docker Engine HTTP API to a configured endpoint.
  That endpoint is *always* a least-privilege socket proxy (allow
  containers/images/networks; deny exec, volumes, build, swarm, system).
  Same-host runs the proxy as a shipped compose-profile sidecar; a remote
  challenge host runs the identical proxy beside its own daemon, reached
  over a private path (VPC / WireGuard / TLS-fronted). One code path — the
  topology is a URL. The app composes every create payload itself
  (`no-new-privileges`, dropped capabilities, cpu/mem/pids limits, a
  dedicated instance network, no volume mounts); challenge authors supply an
  image reference and ports, never raw Docker options, so no user input
  reaches privileged fields.
- **`kubernetes`** — same contract over namespaced workloads with
  NetworkPolicy isolation; ships after the Docker kind (see shipping order).
- **`shared-static`** — no lifecycle; returns fixed endpoints. Covers
  "one always-on nc host" challenges and doubles as the zero-infra kind for
  development and tests.

**`validate()` is a first-class part of the contract**, not a ping. It
returns an ordered list of named check legs, each pass/fail with detail, and
the admin UI renders them individually (the AI panel's two-leg connection
test is the in-repo precedent). For the `docker` kind the legs are:

1. endpoint reachable and API version compatible;
2. privilege posture probe — allowed verbs succeed **and** denied verbs
   (exec, volumes) return errors, proving the proxy's allowlist is actually
   in force;
3. pull a probe image;
4. run and destroy a probe container with the hardened spec;
5. **public reachability** — the backend dials the configured public
   hostname on a port from the configured range, end to end, catching the
   closed-firewall / wrong-hostname class of failure;
6. (HTTP mode, Phase 2) wildcard DNS resolves and the ingress answers.

A failing leg names itself and what to fix. This is the mechanism that makes
"seamless, UI-configured" honest: the one out-of-band step per topology is a
documented bootstrap command, and everything after it is settings plus a
green checklist.

### 2. Concurrency — no new process class

Provisioning is slow but it is async HTTP; it runs as **background-lane work
(ADR-0012)**, never on the request path. The `challenge_instance` row itself
is the job: `requested → provisioning → running → expiring → destroyed`
(terminal failure state `failed`), transitions idempotent and guarded so a
subject holds at most their cap of active instances per challenge. TTL
reaping, orphan GC (backend containers with no matching row, rows with no
matching container) and health checks are periodic work and belong to the
**existing scheduler** — in-process in the single-worker default, the
scheduler sidecar under multi-worker (ADR-0025/0026).

Explicitly rejected: a dedicated instancer daemon. Nothing here needs
sub-second scheduling, and a new always-on process is a real operational cost
for self-hosters. If instancing load ever outgrows the shared scheduler, that
is a tuning problem inside the same design, not a new architecture.

### 3. Unique flags — hashed at rest, resolved before static grading

`flag_mode: unique_per_instance` renders the challenge's `flag_template` at
provision time, injects the plaintext into the instance **once** (env or
file), and stores **only the hash** on the instance row — the same at-rest
posture as static flags. Staff cannot read a live instance flag; the remedy
is re-provisioning. (Rejected: an `EncryptedString` recoverable copy — it
widens who can read live flags for marginal support value.)

Grading resolves in this order: if the challenge is unique-mode, compare
against the subject's *active* instance hash; otherwise (and on fall-through)
the existing static/regex/MCQ paths run unchanged. **First blood and decay
need no semantic change** — both key on which *subject* solved and how many
solves exist, not on flag identity.

Because every instance flag is subject-bound, a wrong submission is also
checked against *other* subjects' active instance hashes for the same
challenge. A match is provable flag sharing and emits
`challenge.flag_shared_detected` for staff and automation. No automatic
penalty — policy stays human.

### 4. Exposure and routing

- **Phase 1 — TCP.** A configured public hostname plus a configured port
  range on the instance host; the allocator treats exhaustion as a clean,
  evented refusal. Connection details render as `nc <host> <port>`.
- **Phase 2 — HTTP.** Wildcard DNS (`*.chal.<domain>`) and a wildcard
  certificate pointing at the **instance host**, with a label-driven ingress
  running on that host (caddy-docker-proxy pattern): the provisioner sets
  routing labels at create time and the ingress configures itself. No
  control-plane round-trip per request, identical behaviour same-host and
  remote, and the platform's own Caddy is untouched. The Kubernetes kind
  maps the same shape onto Ingress + NetworkPolicy.

### 5. Configuration, guardrails, and platform integration

- **Site level** (new admin surface, gated by a new `manage_instance_infra`
  permission — infrastructure credentials are a higher-stakes grant than
  site settings, the auth-providers precedent): provisioner kind, endpoint,
  registry credentials (ADR-0020 `EncryptedString`), public hostname, TCP
  port range, default resource limits, global concurrency ceiling, spawn
  rate limits, egress policy. Ships unconfigured: like the AI module
  (ADR-0023), the module is **inert until an operator configures a
  provisioner**, on top of the per-competition toggle.
- **Per competition**: max alive instances, instance session length
  (default lifetime), and the extension policy (how many extensions / max
  total lifetime). Competitors can extend a running instance from the
  challenge modal within that policy, and see their running instances (with
  expiry countdowns, live over the existing WS rooms) on the challenges
  page.
- **Per challenge**: image reference, exposure and ports, env, lifetime
  override, per-subject cap, flag mode and template — plus a staff
  test-launch that works pre-publish and while the competition is
  `not_started`.
- **Lifecycle ties**: launches require competition `running` (#221 gate);
  `ended` and archival reap and purge instances; pause blocks new launches
  but keeps instances alive. Demo mode force-disables launching (same class
  as `DEMO_DISABLED_ACTIONS`). Every transition emits a §3.2 catalogue event
  with `TRIGGER_PERMISSIONS` entries, is audited, and is pushed to the
  subject over the existing rooms.
- **Portability**: deployment *specs* are authoring content — they ride the
  backup (ADR-0016) and the ctfcli mapping. Instances are runtime state and
  are never exported.

### Shipping order

Phases per #266: foundations and the Docker kind with TCP exposure and
shared flags first (the shippable slice); unique flags, extension, quotas and
HTTP routing second; the Kubernetes kind third, behind the same contract.
The v1.6.0 target is the Docker path end-to-end; `kubernetes` lands in a
following milestone unless capacity allows sooner.

**Status (2026-08-28):** the Docker MVP shipped (Phases 0–1). Phase 2a —
**unique per-instance flags** (§3): provision-time template render + inject +
hash-store, unique-mode grading against the subject's live instance, and
`challenge.flag_shared_detected` — has landed. Remaining Phase 2: HTTP
subdomain routing + wildcard TLS (§4).

## Consequences

- **Easier:** pwn/web-heavy events become viable on Flagpost alone. One
  contract covers three topologies, and moving from same-host to a
  sacrificial challenge host is a two-field settings change plus a bootstrap
  command. No new daemon for self-hosters. The staged validator converts the
  most likely field failures (firewall, hostname, proxy misconfig) into
  labelled admin-UI errors before competitors ever see a connection string.
- **Harder:** a new class of operator-configured outbound dependency (the
  container runtime endpoint — joins SMTP/webhooks/IdPs/AI in `PRIVACY.md`).
  HTTP challenges put a wildcard DNS + certificate burden on self-hosters,
  documented as a prerequisite. The socket proxy cannot inspect create
  payloads — that risk is carried by app-composed hardened specs and the
  recommended remote-host posture, and must be re-examined in the Phase 2
  security pass. Hash-only flags mean staff support answers are
  "re-provision", never "here's your flag".
- **Foreclosed / accepted risks:** egress-deny-by-default will break
  internet-needing challenges unless the per-competition opt-in is used —
  deliberate. Deferring Kubernetes means large events on k8s wait a
  milestone; the kind registry exists precisely so that arrival changes no
  core logic. Windows containers, Attack-Defense rotation and browser
  workstations stay out of scope here and build on this substrate later.

## Amendment: egress model (2026-08-27)

Decision #5 above (and the original §4 exposure text) assumed the instance
network would be `internal: true` — denying egress and control-plane reach at
the Docker layer while published TCP ports "still route (DNAT)". **Live testing
against a real daemon disproved that:** Docker will **not** publish a host port
from a container attached only to an `internal` network — there is no gateway to
NAT through — so an internal network silently breaks the entire TCP-exposure
feature (the `public_reachable` validate leg fails with "probe published no
port"). Internal-network egress-deny and published-port TCP are mutually
exclusive on Docker.

**Corrected decision:** the instance network is a **normal bridge**. Egress-deny
for instances is a **host-firewall** responsibility (drop forwarded traffic from
the instance subnet except the competitor-facing ports; always block the cloud
metadata IP `169.254.169.254`), the same posture CTFd-Whale / kCTF take. The
`egress_policy` setting is retained as operator *intent*: `deny` (default) makes
the `network_isolation` validate leg **remind** the operator to apply firewall
rules — it can't verify them — rather than hard-requiring an internal network
(which it previously, and wrongly, did). An `internal` network remains valid only
for `exposure: none` challenges (no published port). This is a security-posture
change: control-plane isolation and egress-deny are no longer automatic from the
network driver; they are a documented deploy step
(`docs/CHALLENGE_INSTANCES.md`). Everything else in the validate contract —
proxy privilege posture, image pull, hardened probe run, public reachability —
was confirmed working end-to-end against real Docker.

## Amendment: HTTP routing shipped (#319, 2026-08-30)

Phase 2 HTTP (§4) shipped. Concrete choices made while implementing the
"label-driven ingress (caddy-docker-proxy pattern)" the decision left open:

- **Label scheme (pinned).** The docker provisioner emits exactly two
  [lucaslorentz/caddy-docker-proxy](https://github.com/lucaslorentz/caddy-docker-proxy)
  labels on an `exposure: http` container: `caddy = <token>.<chal_base_domain>`
  and `caddy.reverse_proxy = {{upstreams <port>}}` (the first declared container
  port, default 80). No host port is published and the container is attached to
  the normal bridge so the ingress reaches it by IP; TLS is the ingress's
  wildcard cert, not per-label.
- **Per-instance id.** A dedicated 8-char Crockford-base32 `subdomain` token
  (globally UNIQUE column, generate-and-retry in the admission transaction), not
  the instance UUID — short, collision-free, and **unguessable** so a competitor
  can't reach another subject's instance by browsing.
- **Base domain in `InstanceSettings`** (`chal_base_domain`), not env — it's
  host-specific operator config, gated on `manage_instance_infra`.
- **Validate leg 6** (`http_ingress`) probes a synthetic `http-probe.<domain>`:
  DNS resolves + `:443` answers. Injectable, like the TCP dialer.
- **Spawn rate-limit** (§5) landed as a per-subject/per-competition launch
  throttle (`spawn_rate_limit` over a window), event-only on trip
  (`challenge.instance_launch_throttled`) — policy stays human (§3).
- **e2e harness.** `docker-compose.instances-http.yml` + `sslip.io` wildcard DNS
  + Caddy internal CA (`local_certs`) prove the routing locally with no domain or
  real cert; `scripts/e2e-instances-http.sh` asserts a labelled container serves
  200 over TLS at its subdomain. Confirmed working end-to-end.

Not in scope (deferred to Phase 3): the Kubernetes Ingress mapping of the same
exposure shape.

## Amendment: Kubernetes kind shipped (#320, 2026-08-30)

Phase 3 shipped the `kubernetes` provisioner kind behind the unchanged contract
(a new backend is a new kind, not a fork — the whole point of §1), plus ctfcli
portability of the deployment spec and a security-hardening pass with a written
threat model (`docs/THREAT_MODEL.md`). Concrete choices made while implementing:

- **REST over httpx, no client library.** The kind talks the Kubernetes API the
  same way the docker kind talks the Engine API — an injectable
  `AsyncBaseTransport`, so the whole lifecycle and the staged `validate()` are
  unit-tested against a mock transport. Zero new dependencies.
- **One namespace, namespace-scoped RBAC — not namespace-per-instance.** A
  ServiceAccount + namespace-scoped Role (`k8s/instances-rbac.yaml`), denied
  secrets / pods-exec / anything cluster-scoped. Namespace-per-instance would
  need cluster-wide rights — the opposite of the socket-proxy least-privilege
  posture. Per-instance isolation is NetworkPolicy, not namespaces.
- **Deployment + Service + NetworkPolicy (+ Ingress for http) per instance.** A
  Deployment (not a bare Pod) is what makes "health checks + auto-restart" real
  (TCP livenessProbe + ReplicaSet). TCP → NodePort from the same host-port
  ledger as docker; HTTP → Ingress at `<token>.<chal_base_domain>` (the #319
  subdomain scheme); the NetworkPolicy is posted *before* the Deployment to
  minimise the pre-policy window, with a namespace default-deny-egress baseline
  closing the rest.
- **Effective backend = the SITE backend (D7).** A container deployment
  (image/ports/env) is portable across docker and kubernetes, and authors never
  chose infrastructure, so `effective_backend(settings, deployment)` routes an
  orchestrated deployment through the site's configured kind — flipping docker →
  kubernetes is a settings change, no re-authoring. A guard refuses the flip
  while instances are live (their teardown re-homes with it). `shared-static`
  stays per-deployment.
- **Hardened pod (D6):** drop-ALL caps, no-priv-escalation, read-only rootfs,
  `RuntimeDefault` seccomp, no auto-mounted API token, requests==limits. The
  kind **ignores** an author `manifest` fragment — honouring one would bypass
  every pin. Per-pod PID/fd caps have no in-manifest k8s form (kubelet
  `--pod-max-pids`) → operator responsibility, documented, not silently claimed.
- **NetworkPolicy egress (D5)** is the enforced upgrade over docker's
  host-firewall documentation: deny mode = DNS-only; allow mode = everything
  except the metadata IPs (v4 + v6) and — per family, for dual-stack — the
  configured cluster CIDRs. Enforcement needs a policy-enforcing CNI, which the
  new `egress_enforcement` validate leg actively proves (a deny-all probe pod
  with a no-policy positive control, so it can't false-pass on an air-gapped
  node).
- **Staged validate() (D8), seven legs:** reachable, privilege-posture
  (SelfSubjectAccessReview allow/deny matrix — a cluster-admin token fails,
  deliberately), namespace, netpol-support, egress-enforcement, probe-run +
  public-reachability (NodePort dial), http-ingress. The two non-API actions are
  injectable seams reused from the docker kind.
- **e2e harness.** `docker-compose.instances-k8s.yml` boots single-node k3s in
  Docker; `scripts/e2e-instances-k8s.sh` applies the RBAC, mints a token, and
  runs opt-in tests (`backend/tests_e2e/`) that drive the REAL provisioner —
  posture, NetworkPolicy enforcement (k3s's kube-router blocks a deny-all pod),
  NodePort reachability, and a whoami instance reached at its subdomain through
  Traefik.

This closes the last deferral from the #319 amendment. Phase 4 (optional
admin-bot) remains future work; ADR-0036 is now fully realised across docker +
kubernetes.
