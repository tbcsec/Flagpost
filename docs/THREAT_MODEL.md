# Threat model — code-executing subsystems

Two Flagpost subsystems run code an adversary controls; every other subsystem
treats its inputs as data. This document states, for each, what we defend, how,
and what stays the operator's job.

- **Challenge instancing** (#266/#320, ADR-0036) runs **deliberately vulnerable**
  images: an author ships something designed to be exploited, and competitors
  exploit it. The sections below up to [the code judge](#the-code-judge) cover it.
- **The code judge** (#446, ADR-0042) runs **code a competitor wrote**, against
  test data the competitor must not see. See [the code judge](#the-code-judge).

# Challenge instancing

## Assets & trust boundaries

- **The control plane** — Postgres, Redis, the object store, the API. An exploited instance
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

An author's cpu/memory/PID overrides are bounded at authoring — the editor, the
ctfcli import and the backup import alike: finite, whole numbers for memory and
PIDs, and floors of 0.01 CPU / 16 MiB / 16 PIDs — and clamped to the same bounds
again where each provisioner composes the runtime spec, so no stored value
(including one saved before the bounds existed) reaches a runtime as `0`, which
Docker reads as *unlimited* (GHSA-vgrr).

## How the control plane / peers / metadata are isolated

### Docker
**Peer isolation is enforced** for published-port (TCP) and `none` instances
(GHSA-vgrr): each TCP instance gets its **own** throwaway bridge,
`flagpost-net-<instance_id>`, instead of sharing one flat `flagpost-instances`
bridge, and a `none` instance gets no network at all (`NetworkMode: none`) — so a
competitor who gets code execution in their own box has no route to a
neighbour's over the Docker network. Competitor reachability is unchanged: a TCP
instance is still reached through its *published host port* (a normal bridge
NATs it in), never over the shared network. The per-instance bridge is created
before the container, removed with it, and any one orphaned by a crash is swept
by the reaper. This needs no extra socket-proxy scope — `NETWORKS` + `POST`
(already required for the isolation leg and container create) cover network
create/inspect/remove — and the probe leg exercises the whole path at
Test-connection time.

**Egress isolation** (to the internet / control plane / metadata) remains a
**host-firewall** responsibility (ADR-0036 amendment): a normal bridge is
required — an `internal` network can't publish a TCP port — so the operator must
drop forwarded traffic from the instance subnets (the shared bridge and every
`flagpost-net-*` one) except the competitor-facing ports, and always block
`169.254.169.254`. The `network_isolation` Test-connection
leg *reminds* of this; it cannot verify firewall rules. The privilege-posture leg
proves the endpoint is a restricted socket **proxy**, never a raw
`/var/run/docker.sock` (the app can't hold host-root through a mounted socket).

The shared `flagpost-instances` bridge now carries only `exposure=http`
instances (and the Test-connection probe). Docker's default `icc=true` lets
containers on one bridge connect to each other, and `icc=false` would break the
shared Caddy ingress, so HTTP instances are **not** isolated from each other on
the docker backend — treat that bridge as a shared LAN (see Residual risks).
The kubernetes backend enforces peer isolation in-cluster for every exposure.

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
  policy is programmed. NetworkPolicies are additive and the baseline selects
  every instance pod, so its DNS rule carries the same kube-dns scope as the
  per-instance one — a looser rule there would widen every instance's policy
  (GHSA-vgrr; a backend test pins the manifest to the provisioner, and the
  `baseline_policy` Test-connection leg flags a cluster still running an older,
  unscoped copy).

This all depends on a **policy-enforcing CNI**. Flannel *accepts* NetworkPolicy
objects but does not enforce them — so the `egress_enforcement` Test-connection
leg actively runs a deny-all pod and checks it is genuinely blocked (with a
no-policy positive control, so an air-gapped node can't produce a false pass).

## Residual risks (accepted / operator-owned)

- **A non-enforcing CNI** → no isolation. Caught by `egress_enforcement`; the
  operator must run Calico/Cilium/kube-router. *Detected, not prevented.*
- **`k8s_cluster_cidr` unset in allow mode** → peers/control plane reachable by
  IP for internet-enabled challenges. Recommended in the UI; documented here.
- **Kubernetes PID/fd exhaustion** → a fork bomb can pressure the node. Operator
  sets a kubelet `--pod-max-pids`. *(Docker pins this; k8s can't in-manifest.)*
- **Docker HTTP-instance peers share a bridge** → per-instance bridges isolate
  TCP instances (and `none` has no network at all), but `exposure=http`
  instances stay on the shared `flagpost-instances` bridge because the
  caddy-docker-proxy ingress must share a network to reach them by IP. A web-app
  RCE in one HTTP instance can therefore reach a neighbouring HTTP instance.
  Kubernetes has no such gap (NetworkPolicy covers all exposures). Isolating
  Docker HTTP peers too is a scoped follow-up — connect the ingress to each
  per-instance bridge (opt-in, since it needs the operator's ingress container
  named and `CADDY_INGRESS_NETWORKS` widened). Lower risk than the TCP case: an
  HTTP competitor drives the app through the browser, not a shell. *Mitigated
  for TCP/`none`; documented for HTTP.*
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

# The code judge

The code judge (#446, ADR-0042 and its amendment) compiles and runs a
competitor's submission against a problem's test data. Unlike an instance, the
workload is *written* by the adversary, and the most valuable asset is in the
same container as it: the expected answers.

## Assets & trust boundaries

- **The hidden test data** — the inputs and expected outputs of non-example
  tests. A submission that can read them can print the answers and "solve"
  anything.
- **The verdict** — a submission must not be able to report its own result.
- **The judge host and control plane** — as for instancing: no breakout, no
  route to Postgres/Redis/the object store, no orchestrator credential.
- **Fair resource accounting** — a submission must not escape its time, memory
  or output limits (a correctness property for the scoreboard, not a
  confidentiality one).

Two boundaries: the **container** (no network, the Docker posture below),
and inside it the **uid split** between the harness and the submission.

## How one judging runs

One throwaway container per judging, through the same restricted socket proxy
as instancing (`docker-compose.judge.yml`; exec, volumes and build denied, and
"Check connection" verifies it). The backend creates the container, uploads a
tar — the harness, a root-only job file, the test data and the source — starts
it, waits, reads one result line from the log and deletes it. The harness
(`backend/judge_harness`, a static Go binary) is PID 1.

| Control | Judge container | vs. instancing |
|---|---|---|
| Network | `NetworkMode: none`, `NetworkDisabled` | stricter — no network at all |
| Capabilities | `CapDrop: ALL`, `CapAdd: SETUID, SETGID, KILL` — for the harness only | **deviation** — see below |
| Privilege escalation | `no-new-privileges` | same |
| Root filesystem | writable layer, every file root-owned | **deviation** — an archive upload into a read-only rootfs is refused |
| Scratch | tmpfs `/work` (exec, owned by the submission user), `/tmp`, `/var/tmp`, and a pinned 64 MB `/dev/shm` | **deviation** — `/work` is exec-able so a compiled program runs |
| PID / fd exhaustion | `PidsLimit` 256, submission `RLIMIT_NPROC` 128, `nofile` 1024 | tighter |
| Memory | container `Memory` = `MemorySwap` (no swap) as the hard backstop | same |
| Labels | `io.flagpost.judge`, never instancing's `io.flagpost.managed` | instancing's orphan reaper deletes managed containers |

**The uid split is the boundary inside the container.** The harness runs as uid
0 holding only `SETUID`/`SETGID`/`KILL`. Every command it runs on the
submission's behalf — the compile step and each test — goes through a launcher
that applies rlimits, then drops to an unprivileged uid with no supplementary
groups and no capabilities at all, then execs. Each judging gets its **own**
uid, drawn from a reserved range above any real account: the kernel counts a
uid's processes host-wide, so with a shared uid one judging's fork-heavy
submission would eat into a concurrent judging's process cap. So the submission:

- **can't read** the job file or the test data (`/judge` is `0700` root); it gets
  its test input only as an already-open stdin;
- **can't write** the rootfs or the harness (root-owned), only `/work` and the
  temp tmpfs;
- **can't forge the verdict**: its stdout is a pipe to the harness, it can't
  reach the harness's own stdout (`/proc/1/fd/1` needs the harness's uid), and
  the result line must carry a per-judging nonce from the root-only job file;
- **can't signal the harness or regain privilege** (different uid, no caps,
  `no-new-privileges`).

`CAP_KILL` is what lets the harness kill every one of the submission's
processes after each run — including ones that left the process group with
`setsid()` — so an orphan can't hold the output pipe open or carry on into the
next test. The harness is a child subreaper, so every orphan comes back to it to
be reaped, and what each reaped process used is added to the test: CPU burnt in
a child the submission never waits for still counts against its time limit.

**Limits.** CPU time is the time limit (`RLIMIT_CPU`, measured from rusage),
with a wall-clock backstop at 3× + 1s. Memory is the submission's summed
resident set plus growth of every writable tmpfs — `/dev/shm` included — since
the test began (so data can't be parked in files to dodge the limit), sampled
every 10 ms, with the
container's cap behind it and the submission's OOM score raised so the kernel
picks it, never the harness. Output is read through a capped pipe; a test's
stderr is discarded and never returned (it could echo hidden input). Files are
capped by `RLIMIT_FSIZE`. The harness returns a program's output only for
example tests that run before any hidden test — tests share `/work`, so a later
test's output could otherwise carry what the program saw in a hidden one — and
the read API shows output, time and memory for examples only — including in a
judging's maxima, which over every test would leak what the hidden tests cost
(and through that, what the program saw). The compile step has its own CPU, wall and memory
budget, so a source crafted to make the compiler balloon gets a compile error.
A fork bomb hits its own `RLIMIT_NPROC` long before
the container's pid limit, so the harness can still start the threads it needs
to report.

All of this is exercised against a real daemon by
`backend/tests/test_judge_executor_e2e.py` (opt-in), including the hostile
probes: reading test data or the job file, writing the harness or rootfs,
network egress, `setuid(0)`, signalling PID 1, forging a result line, CPU and
sleep loops, memory hogs in RAM and in files, output floods, oversized files, a
fork bomb, and orphans holding stdout.

## Residual risks (accepted / operator-owned)

- **Shared kernel.** As for instancing: a container breakout 0-day defeats the
  posture. Recommended: run the judge's Docker host apart from the control
  plane for a high-stakes event. *Mitigated, not eliminated.*
- **Language images are trusted.** An administrator chooses each language's
  image (`manage_judge_infra`); the image's own binaries run as the submission
  user. A malicious image could misjudge. Images are pulled anonymously (the
  instancing registry credential is never sent), so a private image must be
  pre-pulled on the judge host. *Operator-owned, like any image.*
- **The submission's process cap is per uid, host-wide.** Each judging draws
  its own uid from a reserved range (100000–1099999), so two judgings colliding
  only share that cap; nothing else is shared, since each container sees only
  its own processes. *Accepted* — and keep other workloads off that range.
- **Memory is sampled summed RSS.** Pages shared between a submission's
  processes are counted once per process, so a multi-process submission is
  measured generously against its limit; and a combined peak across several
  processes lasting under the 10 ms sampling interval can slip past (a single
  process's peak is always caught from its rusage). Typical contest code is a
  single process, and the container's memory cap bounds the rest. *Accepted.*
- **Tests share `/work`.** Files a submission writes during one test are still
  there for the next. It can only see its own inputs, so this leaks nothing,
  but tests aren't hermetic. *Accepted.*
- **Timing is good, not finals-grade** (ADR-0042 consequences). CPU-time
  accounting removes most contention, but a submission within a few percent of
  its limit can flip under heavy host load. *Documented for operators.*

**Submitted code** is stored in object storage under the competition's prefix,
readable by the submitter (and their team) and by staff with `judging_view`,
and deleted with its challenge, its competition or its author. An
examples-only run's source is deleted as soon as it's judged.

## Backup / export boundary

Code submissions and judgings are runtime state and never exported (an
accepted judging's score rides the backup in its ordinary `Submission` row).
Problems and their test data are portable authoring content and ride the backup
(validated on import; a row is only ever pointed at its own re-stored zip). The
judge's site configuration — the endpoint and the language registry (an image
plus commands the judge runs) — is never exported, so a backup can't plant a
language (the GHSA-x8v4 class).
