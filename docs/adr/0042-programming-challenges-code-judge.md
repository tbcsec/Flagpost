# ADR-0042: Programming challenges — judge execution model, queue, and grading integration

**Status:** Proposed
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
