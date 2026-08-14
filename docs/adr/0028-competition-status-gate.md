# ADR-0028: Competition status is an explicit gameplay gate; the schedule drives it

**Status:** Accepted
**Date:** 2026-08-14
**Architecture reference:** `ARCHITECTURE.md` §13.1 (competition lifecycle), §13.2 (gameplay state)

## Context

Until now a competition had **no state that gated gameplay**. `start_at` /
`end_at` were purely informational: they drove a *derived* status label in the
admin overview and fired one-shot `competition.started` / `competition.ended`
audit events at their boundaries, but **nothing checked them** for challenge
viewing, flag submission, or the scoreboard. The only manual gate was `paused`
(a temporary halt within a run). So a competition with a future start time still
let competitors solve challenges, and an organiser had no way to open or close a
competition on the day except by editing schedule datetimes.

We want new competitions to start closed, a clear "not started / ended" gate on
the competitor surface, and a manual Start/Stop for judges that coexists with the
schedule, pause, and freeze — flexible run-day control (#221).

The tension: an explicit status could either **replace** the schedule or
**duplicate** it, and however we reconcile them, existing deployments must not
have a live competition silently closed or a finished one reopened on upgrade.

## Decision

Add an explicit **`Competition.status`** — `not_started` → `running` → `ended`
(reversible) — that **is the gate**. It gates two tiers differently:

- **Play** (view/open challenges, submit flags) is open **only while `running`**;
  otherwise the challenge surfaces return a closed response and the UI shows a
  "hasn't started / has ended" message.
- **Results** (the scoreboard and the dashboard solve ticker) open when the
  competition **starts** and **stay readable after it ends** — the final board is
  read-only, not closed (CTF convention). They're closed only while `not_started`.

Staff holding `challenge_edit` **bypass** the gate on both tiers, so organisers
build before the start and review after the end (the same bypass `paused` uses).

**The schedule drives the status, and a manual action overrides it.** New
competitions default `not_started`. The scheduler tick auto-transitions
`→ running` at `start_at` and `→ ended` at `end_at`, reusing the existing
`started_event_fired` / `ended_event_fired` flags. A judge's manual Start/Stop
(routes `POST /competitions/{id}/start|stop`, permission `manage_schedule`) is
**authoritative**: it sets the status and claims the matching boundary flag, so
the scheduler will not re-fire or undo the decision — once a judge intervenes on
a boundary, they own it (a consequence: after a manual stop, a subsequent
re-start is under manual control and a still-scheduled `end_at` won't auto-close
it again — the judge stops it manually).

The `*_event_fired` flags track whether the **lifecycle event has been emitted**,
so `competition.started` / `competition.ended` each fire **exactly once** over a
competition's lifetime (first occurrence, manual or scheduled) for audit +
automation. A reversible re-start / stop→start→stop flips `status` (the gate) but
does **not** re-emit, so side-effecting lifecycle automations (email results,
post a closing announcement) never double-run.

The gate is enforced at the competitor **entry points** — the challenge list,
challenge detail, and flag submission (`is_playable`, running-only); the
scoreboard and solve ticker (`has_started`, running-or-ended) — **not** inside the
shared `load_visible_challenge` loader, so post-event feedback that legitimately
reads an already-seen challenge (ratings, revealed hints, attachment re-download)
keeps working after the end. The AI competitor assistant shares the one `running`
definition (`is_competition_active` → `status == running`). `paused` and
`scoreboard_frozen_at` remain **orthogonal** axes, unchanged.

Existing competitions are **backfilled on migration** from their schedule/now
(`ended` if past `end_at`; `running` if started or open-ended; `not_started` if
the start is still in the future), with the dedup flags aligned so the first
post-migration tick can't contradict the derived status.

## Consequences

- **Positive:**
  - A real, manually-controllable gate for run-day operations, composing cleanly
    with pause (temporary halt) and freeze (board only).
  - One source of truth: the schedule and the manual buttons drive the same
    field; the gate reads one thing (`status == running`).
  - The gate lives at the data layer (submission guard, the shared
    `load_visible_challenge` choke point, the challenge list, the scoreboard
    read), not per-endpoint memory — staff bypass is the single `challenge_edit`
    rule the frontend mirrors exactly.
- **Negative / cost:**
  - **The schedule now gates.** A scheduled-but-not-yet-started competition will
    close play where before it did not — an intended behaviour change to call out
    in release notes. The migration backfill keeps *existing* competitions from
    being disrupted, but operators relying on the old "schedule is informational"
    behaviour should know the semantics changed.
  - The scheduler now writes `status` (not just event flags) when a boundary is
    crossed — still only on the crossing, so steady-state ticks are unchanged.
- **Forecloses:** nothing new. A future per-phase lifecycle (e.g. a separate
  "results published" state) would extend this enum rather than reintroduce
  schedule-derived gating.
