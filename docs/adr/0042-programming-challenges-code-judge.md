# ADR-0042: Programming challenges — judge execution model, queue, and grading integration

**Status:** Proposed (amended 2026-10-14 after the #448 gating spike — §7's
container posture and the harness are revised; see the Amendment)
**Date:** 2026-10-14
**Tracking:** epic #446 (#447 schema/authoring, #448 executor/pipeline, #449
competitor UX, #450 jury console, #451 problem packages)
**Architecture reference:** `ARCHITECTURE.md` §3 (events), §6 (tenancy), §7
(RBAC), §11 (modules), §15 (trust tiers), §16 (instancing). A programming-
challenges section is added to `ARCHITECTURE.md` with the Phase 1
implementation.

## Context

Every Flagpost challenge today is graded by comparing a submitted string to a
stored flag: static hash, regex, or multiple-choice (`utils/flags.py`).
Grading is synchronous, cheap, and total — the submit route returns the verdict
in the same request. That model cannot express a *programming* challenge, where
the competitor submits source code that must be compiled and executed against
test data under time and memory limits before any verdict exists.

Adding this forces seven decisions at once, entangled enough to record
together.

1. **What executes the code, and under what contract.** The `instances` module
   (ADR-0036) already runs adversary-controlled code in hardened containers via
   a provisioner-*kind* registry. Does judging reuse `Provisioner`, or define a
   sibling contract?
2. **What drives the work.** Instancing rides the event bus's background lane
   (`@event_bus.on(..., background=True)`). Judging runs are routinely longer
   than instancing's container start, and the bus imposes a hard per-handler
   timeout.
3. **How the queue is represented** without adding a broker to a stack whose
   default deployment is one process and SQLite.
4. **How a verdict becomes a score** without forking the scoreboard, decay,
   first-blood, freeze, skills and analytics read paths — all of which key off
   one predicate on one table.
5. **What the resource envelope is.** The owner's constraint is explicit:
   minimise the resources needed to judge a submission. A fleet of dedicated
   judgehosts is the reference architecture in this space; it is not an
   acceptable floor for Flagpost.
6. **Which module tier each part belongs to** — an optional per-competition
   module, a required-core one, or not a module at all.
7. **Where the trust boundary sits** now that a second subsystem runs
   adversary code — and that this one runs code written *by the competitor*,
   not merely chosen by the author.

The owner has additionally fixed the product ordering: programming challenges
ship first as an **additive challenge type on the existing points scoreboard**,
so hybrid events (security + programming challenges in one competition) work;
**ICPC-style ranking** (problems solved, ties broken by penalty time) follows
as a separate competition-level scoring mode in a later milestone. This ADR
covers the judge; the ranking mode gets its own ADR.

## Decision

Programming challenges are a new **optional, inert-by-default module**
(`judge`) that adds a challenge type graded by executing submitted code in an
ephemeral hardened container. Seven specifics:

**1. A sibling executor contract, not the provisioner contract.** A new
`JudgeExecutor` ABC (`run(job) -> JudgeResult`, `validate() -> list[CheckResult]`)
with its own class-decorator registry, mirroring the *shape* of
`utils/provisioners.py` but not its interface: `Provisioner` is built around
long-lived, network-exposed instances (`endpoints`, `status`, `destroy`,
`list`), whereas a judging is a one-shot run-to-completion with captured
output. The Docker transport, `DockerConfig`, socket-proxy posture, container
hardening recipe and `CheckResult`/`validate()` idiom are reused directly.
Registry lookup goes **through** the registry — the `if kind == "docker"`
branching in `instance_service.provisioner_for` is a wart we do not replicate.

**2. A dedicated worker loop, not the event-bus background lane.** The bus
wraps *every* handler, background included, in
`asyncio.wait_for(..., timeout=10.0)` (`DEFAULT_HANDLER_TIMEOUT`). Any judging
slower than ten seconds would be cancelled mid-run. (Instancing inherits this
and is silently affected — filed separately as #452.) Judging is therefore
driven by its own asyncio loop, started where the scheduler starts
(in-process when `WEB_CONCURRENCY<=1`, in the `python -m scheduler` sidecar
otherwise — ADR-0025/0026/0031), polling at a short interval so a competitor's
submission starts within ~1s. The shared 60s scheduler tick is too coarse to
*drive* judging, so it instead carries a `reap_judgings` step for stuck-row
reclamation, exactly as it carries `reap_instances`. Events are still emitted
for audit, automations and WS — they just do not execute the work.

**3. The `Judging` row is the queue.** No broker. A judging is claimed with an
atomic conditional `UPDATE ... WHERE status='queued'` checking `rowcount` (the
`routers/invite_links.py` `max_uses` pattern), which is strictly safer than the
read-then-assign claims used by the instance and report-job paths, and works on
SQLite. `claimed_at` acts as a visibility timeout; the scheduler reclaims
anything stuck.

**4. An accepted verdict writes an ordinary `Submission` row.** `Submission` is
read by ~15 modules — scoreboard, timeline, skills, analytics, public insights,
reports, certificates, backup — all keyed on
`is_correct AND NOT is_duplicate` plus `points_awarded`. The judge therefore
does not fork any of them: on Accepted it inserts a normal awarded
`Submission`, through the same nested-savepoint / `IntegrityError`-to-duplicate
path and the same dynamic re-value sweep as a flag solve, and emits
`challenge.solved`. That award path is extracted from
`routers/submissions.py:submit_flag` into a shared helper rather than
duplicated. The source code does **not** live in `Submission.value` (capped at
500 characters); it lives in a `CodeSubmission` row with the source in object
storage.

Crucially, the awarded row's `created_at` is **backdated to the code
submission time**, not the verdict time. `created_at` doubles as the solve time
across every read path, so grading latency would otherwise distort first-blood
ordering, freeze cutoffs and — once ICPC mode exists — penalty time. Nobody is
penalised for queue depth.

**5. Lightweight by default, scale-out by configuration.** `max_concurrent_judgings`
defaults to **1**: one judging at a time, bounding peak cost to one core plus
one memory limit, and keeping time limits meaningful on shared hardware. Idle
cost is zero — nothing runs between submissions; the only standing footprint is
the language image cache. Fairness comes from **CPU-time accounting** (measured
by an in-container harness via `getrusage`, with a wall-clock backstop at a
multiple of the limit) rather than core pinning, which is what makes dedicated
judgehosts unnecessary. Further savings are structural: one container per
*judging* (compile once, fresh process per test) rather than per testcase, and
lazy judging that stops at the first failing test, samples first.

**6. The judge is an optional module; the ranking mode is a competition
column, not a module.** `judge` becomes the eighth optional module —
per-competition toggleable via `competition_modules`, routes `_guard()`ing to
404 when disabled, inert until an operator configures an executor and a
language. That is the right shape for a feature surface with infrastructure
prerequisites, and it matches `instances` exactly.

ICPC-style ranking, when it arrives, is deliberately **not** a module. It is a
`Competition.scoring_mode` column (`points` | `icpc`) plus a branch inside the
**required-core `scoring` module**, for two reasons. First, a module toggle
answers "is this feature available here?" and may be flipped mid-event, whereas
a ranking mode must be stable — flipping it mid-contest silently re-ranks
everyone and changes the meaning of stored data. Second, and decisively, the
module system cannot express it: modules `provide` routers and event listeners
only, with no mechanism to *replace* a core read path, and ICPC mode is
precisely a replacement of `compute_scoreboard`'s aggregate and `sort_key`. The
precedent is `participation_mode` — a competition-level mode, chosen at
creation, that changes how scoring groups subjects, implemented as a column.

A consequence worth stating: the two are **orthogonal**. ICPC-style ranking has
no dependency on programming challenges and works over flag challenges, so all
four combinations are meaningful (points+flags today, points+judge for hybrid
events, icpc+flags for an ICPC-ranked CTF, icpc+judge for a pure programming
contest). `scoring_mode` is settable only while `status == "not_started"` and
frozen thereafter, consistent with ADR-0028. Disabling `judge` mid-competition
404s its surfaces but leaves existing solves in `Submission`, so the scoreboard
still counts them — the same behaviour as disabling `instances` mid-event.

**7. Trust posture equals Docker instancing, and is documented as such.** The
judge container reuses the fixed `_container_body` hardening (`CapDrop: ALL`,
`no-new-privileges`, `ReadonlyRootfs`, `PidsLimit`, `Memory`, `NanoCpus`,
`AutoRemove`, no binds, no mounts) with two deliberate deviations: network mode
is **always `none`** (a judge never needs egress, which also prevents fetching
answers or exfiltrating test data), and the writable tmpfs workdir is mounted
**without `noexec`**, since a compiled submission must be executable. Code and
test data enter, and results leave, without granting network or exec: the
container is created, a tar of source plus test data is uploaded via the Docker
API archive endpoint, the container is started with the harness as its `Cmd`,
and a JSON result line is read back from container logs. `docs/THREAT_MODEL.md`
is retitled from instancing-specific to cover both code-execution subsystems,
with a judge section and its own residual-risk list.

## Consequences

- **Positive:**
  - Idle resource cost is zero and per-judging cost is one bounded container,
    so a single-VPS deployment can host a hybrid event. No broker, no new
    process class, no fleet.
  - Scoreboard, dynamic decay, first blood, freeze, brackets, CTFtime, the
    skills web and the staff submissions browser work **unchanged**, because a
    verdict lands as an ordinary awarded `Submission`.
  - The executor registry means an external judgehost kind (and a Kubernetes
    kind) is a new class, not a rewrite — the same escape hatch instancing has.
  - The queue is a table, so it survives restarts, is inspectable in the jury
    console, and needs no infrastructure the stack does not already require.

- **Negative / cost:**
  - **Timing fairness is good, not finals-grade.** CPU-time accounting removes
    most host-contention sensitivity, but a submission sitting within a few
    percent of its limit can still flip verdict under heavy load. Mitigations
    are generous limits (per-language time multipliers) and, for events that
    care, the external judgehost kind. This must be stated plainly in operator
    docs.
  - **Serial judging means queueing under load.** With a 1-judging default and
    lazy judging, throughput is roughly 20–30 judgings/minute; a large
    programming-heavy event will need the concurrency raised or judgehosts.
    Competitors see an explicit queue position rather than a silent delay.
  - **The container I/O channel is the main implementation risk**, gated as a
    spike at the top of #448. The upload-tar
    plus read-logs design depends on the Docker socket-proxy allowlist
    permitting the archive endpoint (`EXEC` and `VOLUMES` are denied by design,
    so neither `docker exec` nor a bind mount is available). This is gated by a
    spike before the executor work; the fallbacks are a storage-only egress
    allowance enforced by network policy, or a per-judging image build
    (rejected on latency grounds unless nothing else works).
  - **CPU/memory accounting is net-new.** Nothing in the codebase reads
    container stats or cgroups today, so the in-container harness is original
    code and needs its own tests.
  - A judging row's state machine, reaper rules and stuck-row handling are a
    second instance of a pattern that now exists three times (instances,
    certificate/report jobs, judgings) without a shared abstraction. Accepted
    as duplication for now; a generic job runner is a later refactor, not a
    prerequisite.

- **Forecloses:**
  - Running genuinely untrusted *third-party module* code (ARCHITECTURE §15
    Tier 3) remains out of scope and is not advanced by this work; the judge
    runs competitor code under a posture the platform already operates, not
    arbitrary code with platform privileges.
  - Per-testcase partial scoring, interactive problems, custom output
    validators and the CCS Contest API are explicitly deferred; the verdict
    pipeline is designed to accept a pluggable validator so they remain
    additive.
  - ICPC-style ranking is **not** decided here. This ADR keeps programming
    challenges on the points scoreboard; the competition-level scoring mode is
    a separate decision and a separate ADR.

## Open question for the record

Instancing events are namespaced under the challenge entity
(`challenge.instance_requested`). Judging events are proposed as their own
entity (`judging.queued`, `judging.completed`, …) because a judging is a
first-class record with its own lifecycle, not a property of a challenge. This
is a small, deliberate divergence from the instancing precedent.

## Amendment: gating-spike outcome — container posture and the harness (2026-10-14)

The executor's riskiest assumption — getting code and test data into a judge
container and a result out, through the socket-proxy, with no exec, no volumes
and no network — was spiked before any executor code, as #448 required. The
channel works. Two of §7's assumptions did not survive contact, and one gap had
to be closed. Full results, with the probe table, are on #448.

**What held.** Create → `PUT /containers/{id}/archive` → start →
`POST …/wait` → `GET …/logs` → delete, all through the production proxy
allowlist (its `POST=1` covers `PUT`). Overhead per judging is ~10 ms to create,
<10 ms to upload and ~0.3 s from start to exit, which confirms "one container
per judging" (§5).

**Revised: the judge container keeps a writable layer.** Docker rejects an
archive upload into a read-only root filesystem (`400 "container rootfs is
marked read-only"`), and copying into a tmpfs is unsupported (a tmpfs is
mounted at start, so it would shadow the upload anyway). `ReadonlyRootfs` and
the upload channel are mutually exclusive, so the writable layer stays — and
its protective role moves to the uid split below. Everything in the rootfs is
root-owned, so the submission cannot write it regardless.

**Revised: the harness and the submission run as different users, which needs
three capabilities.** §7 implied the instancing recipe's bare `CapDrop: ALL`.
Under that, the harness and the submission share a uid, so a submission could
read the test inputs or job file, overwrite the harness, or forge its result
line — and the harness cannot switch uid at all. The judge container instead
runs:

- the **harness as uid 0 with only `CAP_SETUID`, `CAP_SETGID` and `CAP_KILL`**
  (all else dropped, `no-new-privileges` on). `SETUID`/`SETGID` let it run each
  test's submission as **uid 65534**; `KILL` lets it reap the submission's
  process group, without which a submission that forks orphans holding its
  output open stalls the harness until they exit (30 s in the spike; 17 ms with
  `KILL`);
- the **submission with no capabilities at all** (`CapEff`/`CapPrm` = 0,
  `setuid(0)` refused), under `RLIMIT_CPU`/`RLIMIT_AS`, with CPU measured from
  the child's rusage (killed by `SIGXCPU` at 0.999 s against a 1 s limit);
- job data and test inputs in **root-only (`0700`) directories**, the source
  world-readable, and scratch in a **`/work` tmpfs owned by uid 65534** with
  `exec` allowed.

A hostile submission was blocked from every probe that matters: reading inputs,
writing the rootfs or the harness's directory, forging the harness's output via
`/proc/1/fd/1`, signalling the harness, `setuid(0)`, network egress, an
unbounded memory hog (`RLIMIT_AS`) and a fork bomb (`PidsLimit`). The uid split,
not a read-only filesystem, is now the trust boundary inside the container.
`AutoRemove` is off (logs are read after exit), the harness's result line
carries a per-judging nonce from the root-only job file as defence in depth, and
the harness reads submission output under a cap rather than buffering it whole.

**Decided: the harness is a static Go binary, uploaded per judging.** The spike
harness was Python, which stock compiler images (C/C++, Java) don't have. Of the
three options — a static binary uploaded with each judging, Flagpost-published
per-language judge images with a Python harness baked in, or requiring operators
to build images that include Python — the owner chose the first. The harness is
written in **Go** (statically linked, `CGO_ENABLED=0`), built in a stage of the
backend image's Docker build for amd64 and arm64, and uploaded into each judge
container alongside the source. Operators point a language at a **stock image**
(`python:3.13-slim`, `gcc:14`, …) and Flagpost publishes no new images.

This adds a language to the stack that ARCHITECTURE §2 fixes; the harness is a
self-contained supervisor with no runtime role in the backend, and §2 is updated
alongside its implementation in #448. The cost is a toolchain stage in the
backend build and a second language to review.

**Consequences.** Compared with Docker instancing, the judge container now
deviates from the shared hardening recipe in four deliberate ways: no network,
an exec-able scratch tmpfs, a writable layer, and three added capabilities. Each
is justified above, and `THREAT_MODEL.md`'s judge section should record them as
such rather than describing the judge as "the instancing posture". The
"embedded executor needs no new infrastructure" property still holds: nothing is
added to the deployment, only to the build.

## Amendment: problem test data is one zip per problem (2026-10-14, #447)

The issue sketched a `JudgeTestcase` row per test case with its input and
expected output as separate objects. Authoring (#447) instead stores **one
test-data zip per problem** — the ICPC/Kattis package layout,
`data/sample/NNN.in|.ans` then `data/secret/NNN.in|.ans` — as a single object
referenced by the `judge_problems` row, which also caches a manifest (stable
id, example flag, sizes) so listing never opens the zip.

Three things decided it. The backup's object side-car carries **one object per
row**, so a problem rides export/import, clone and the retention purge exactly
as an attachment does, with no special-casing. The zip **is** the interchange
format problem-package import (#451) reads. And the executor (#448) fetches
**one object per judging** instead of 2 × N. File names inside the zip are
re-derived from position on every write, so they always sort in judging order
(examples first).

The cost is that every test-case edit rewrites the whole zip. That is bounded
(16 MB per file, 64 MB per problem) and authoring-time only; edits take a row
lock so concurrent editors can't lose each other's changes, and the new zip is
stored under a fresh key and the old one deleted only after commit, so a
failure part-way never leaves the row pointing at a partial object.

## Amendment: the queue and scoring as built (2026-10-15, #448)

Three refinements of the issue text, made while building the pipeline.

**States are `queued → running → done | failed`.** The issue listed
`claimed`, `compiling` and `running` separately. The claim itself moves a
judging to `running`, and the container is opaque while it runs, so compile
and run aren't separately observable from outside it; extra states would be
names for moments nobody can see. `done` means a verdict about the
submission was reached; `failed` means none could be, after retries, and is
reported as `internal_error`.

**Every scored verdict is a `Submission` row, not only an accepted one.** §4
specified an awarded row on Accepted. A wrong answer is recorded too, as an
unawarded row (`is_correct = false`), through the same shared path. That keeps
the flag path's invariant — every graded attempt is a row — so attempt counts,
challenge health and analytics treat code and flags alike, and #450's rejudge
can reconcile a row in either direction. `internal_error` is never recorded:
it isn't a verdict about the submission.

**Two kinds of submission.** `submit` is judged against every test and scored;
`run` against the examples only and never recorded or scored — #449's "try it
on the samples" button, which needs the program's actual output on an
example. The harness returns output only for examples that run before any
hidden test (tests share the scratch directory, so a later test's output could
carry what the program saw in a hidden one), and the read API shows it for
examples only.

