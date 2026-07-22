# Tier 3 — "Pre-Launch Polish + the Big Deferred Subsystems": Phased Plan

## Context

Tier 2 is complete (dashboard, tickets, presence, site-wide theming, custom
roles). Tier 3 (`docs/ROADMAP.md` items 22–28) was originally "pre-launch
polish", but an owner revision pulled three tier-sized subsystems that had been
deferred past MVP **up into Tier 3**: the **full automation engine** (#25, §5),
**dashboard drag-and-drop** (#26, §10.2–10.5), and **collaborative rich-text /
CRDT editing** (#27, §4.2). So Tier 3 is no longer "polish" — it's three of the
largest lifts in the architecture *plus* the polish items (survey, analytics,
onboarding, and a final accessibility/optimization pass).

**Owner scope decisions for this tier (confirmed):**
- **Build order: automation engine first.** It's the riskiest item and it
  unblocks two others — the survey "trigger" (#22) and any future
  email/push notification delivery (§4.4) are both automation *actions*. Doing
  it first also forces the ADR-0009 dispatch decision early, while the rest of
  the tier is small enough to absorb the churn.
- **Full spec on both heavy subsystems.** Automation ships the §5.5 **visual
  node-based rule builder** and **all eight action types** (§5.3), not a
  form-only subset. CRDT ships **both** the staff-facing and team-facing cases
  (§4.2) in this tier, not one side first.
- **One phased plan doc** (this file), mirroring `phase_2.md`. Automation is big
  enough that it spans several phases (0–3); the rest are one phase each.

**Two pre-existing gaps this tier has to close first (surfaced while planning):**
- **`emit()` is not actually non-blocking.** `utils/event_bus.py` `await`s all
  handlers via `asyncio.gather` (with a 10 s per-handler timeout). A slow
  webhook action would hold the triggering request. ADR-0009 explicitly flagged
  the automation `webhook` action as the trigger for resolving this — so a
  dispatch refactor is a **prerequisite** for the engine, not an afterthought.
- **The §4.4 in-app notification center is still placeholder.** The bell in
  `app-shell.tsx` renders `NOTIFICATIONS` from `lib/placeholder-data.ts`; there
  is no notifications table, no per-user read/unread state, and no
  `/ws/user/<id>` room. The automation `notify` action needs a *real* one, and
  §4.4 says this baseline should exist independently of automations anyway — so
  it's a genuine Tier-2 gap this tier closes up front.

Governing docs: `ARCHITECTURE.md` §5 (automation), §4.4 (in-app notifications),
§4.2 (collaborative editing / CRDT), §10 (dashboard customization), §3 (event
bus), §11.3 (kernel/required-core/**optional module** split — automation and
feedback are the first genuinely *optional*, per-competition-toggleable
modules), §7 (RBAC), §13 (domain model). ADR-0005 (single-process bus limits)
and ADR-0009 (synchronous dispatch) are both squarely in play in Phase 0.

Conventions held throughout (unchanged from Tiers 1–2): every mutation emits a
past-tense `<entity>.<verb>` event already in §3.2 (add new ones there first);
every tenant-scoped table uses the competition-scoped mixin and every query
filters by `competition_id`; permission checks go through `require_permission`;
one router + one hook module per domain; colours/spacing from tokens; new
backend features register through the module loader (§11.1). One migration and a
green pytest + vitest + tsc + eslint run per phase; one commit per phase.

---

## Phase 0 — Notification center + event-dispatch groundwork (§4.4, §3.1, ADR-0009) — ✅ DONE

The foundation the automation engine stands on. Nothing user-visible from
automations yet — this closes the two gaps above so Phases 1–3 have a real
`notify` target and a dispatch model that can carry a slow webhook.

- **Event-dispatch refactor (resolve ADR-0009 → new ADR-0012).** Make `emit()`
  genuinely non-blocking for background handlers while keeping the audit log
  synchronous and lossless. Preferred shape (decide in the ADR): split
  subscribers into **sync-critical** (audit — awaited inline, mutation depends
  on it) vs **async-background** (notifications, automations, webhooks —
  scheduled fire-and-forget with isolated failure + the existing per-handler
  timeout). A durable **outbox** for at-least-once delivery is the heavier
  alternative; the ADR picks one and states the durability tradeoff (today the
  audit log is lossless *because* dispatch is synchronous — don't regress that).
  This is single-process still (ADR-0005 unchanged); horizontal fan-out stays
  out of scope.
- **Real in-app notification center (§4.4).** `Notification` model (per-user,
  `competition_id` nullable, type, payload, `read_at`); REST list + mark-read /
  mark-all-read; the **`/ws/user/<user_id>` per-user room** (§4.4) so
  notifications push live. Replace the placeholder `NOTIFICATIONS` with a real
  `use-notifications.ts` hook feeding the existing bell UI; keep the Tier-2
  ticket audio cue wired to the same stream. This is the §4.4 baseline finally
  made real — it is *not* an automation feature, it just had to wait for a
  consumer.
- Migration: `notifications` table. No new permission (a user reads their own).
- Tests: dispatch ordering/isolation (sync-critical awaited, background
  scheduled, one handler's failure doesn't block others), notification
  create/read/scoping RBAC, the per-user WS push.

## Phase 1 — Automation engine: model, evaluation, action executors (§5.1–5.3) — ✅ DONE

The engine core, as an **optional system module** (§11.3) — the *first* module
that carries a real enable/disable toggle and declares a manifest **dependency**
(the event bus), exercising the loader's dependency-refusal path for the first
time.

- **Model + migration.** `AutomationRule` per §5.1 (`trigger_type`,
  `conditions` JSON `[{field, operator, value}]`, `actions` JSON `[{type,
  ...config}]`, `is_enabled`, `competition_id` nullable = global rule,
  `owner_user_id` nullable = personal rule, `trigger_count`,
  `last_triggered_at`). Generic `JSON` columns for SQLite/Postgres parity
  (ADR-0006).
- **Evaluation (§5.2).** The engine subscribes to the event bus (wildcard), and
  on each event loads enabled rules matching `trigger_type`, evaluates
  `conditions` against the payload, and runs `actions` for matches — a *consumer*
  of the bus, not a parallel system. Increments `trigger_count` /
  `last_triggered_at` and emits **`automation.rule_triggered`** (already in
  §3.2). Runs on the async-background lane from Phase 0.
- **All eight action executors (§5.3).** `notify` (→ Phase 0 center),
  `release_hint`, `unlock_challenge`, `create_ticket`, `update_score`,
  `award_achievement`, `send_email`, `webhook`. Each mutating action must itself
  emit its §3.2 event — **two need new event types added to §3.2 first**
  (candidates: `score.adjusted` for `update_score`, `achievement.awarded` for
  `award_achievement`); `award_achievement` also needs a small **achievement
  store** and `send_email` needs **net-new SMTP delivery** (config + async
  mailer) — treat those two as the trailing, infra-heavy executors.
  `webhook` lands here but its hardening is Phase 2.
- **RBAC.** Flip `automation_view` / `automation_create` / `automation_edit`
  from `reserved` to enforced (add `automation_delete` if the CRUD needs it, to
  §7.1 first). Personal rules (`owner_user_id`) let a judge/captain manage their
  own without elevated automation perms (§5.1).
- Router + `use-automations.ts` hook (already anticipated in §8). No UI yet
  beyond a minimal list — the builder is Phase 3.
- Tests: trigger→condition→action matching, scoping (global vs competition vs
  personal), each executor, the reserved-perm flip, the new events, module
  enable/disable gating a rule from firing.

**As built (deviations worth knowing):** `trigger_type` is the verbatim §3.2
event name (no parallel enum; `utils/event_catalog.py` mirrors the vocabulary
in code, `automation.*` excluded as triggers). Personal rules are restricted to
**notify-self** (§5.1 note added — they're creatable without automation perms,
so they must not run privileged actions). The new events grew to include
`hint.released` (the `release_hint` action's mutation — a granted reveal at
`cost_charged=0`) and `module.enabled`/`module.disabled` (the per-competition
toggle, `competition_modules` table, kernel-mounted router since the loader is
kernel). A global rule requires the automation perms via a *global* assignment.
Basic loop guards landed here (automation.* never triggers; cascade-depth cap
`automation_max_depth=3`) — Phase 2 still owns the fuller §15 story. Judge
gained the three automation perms (startup role re-sync propagates them).

## Phase 2 — Webhook action hardening (§5.4) — ✅ DONE

Its own phase because the threat is specific and adversarial: webhook targets +
templates are admin-authored, but the **values substituted in** (team names,
challenge names, ticket titles) are competitor-controlled by design.

- **Per-call SSRF blocklist** (revalidated every call, not just at rule save —
  DNS can rebind) — no loopback/internal/link-local targets. Consider a small
  ADR for the egress policy.
- **Strip caller-uncontrollable headers** from admin header sets
  (`Authorization`, `Cookie`, `Host`, `X-Forwarded-*`) so a rule can't forge
  origin or smuggle credentials.
- **Content-Type-aware escaping** of substituted values (JSON string escaping
  for JSON bodies) so a team named `","admin":true` can't inject sibling keys.
- **Defang chat rendering tokens** (Slack/Discord/Teams broadcast/mention
  tokens, markdown links) in substituted values so a team can't rename itself to
  `@everyone` and mass-ping through an organiser's rule.
- Tests: adversarial team/challenge names through each escaping path; SSRF
  blocklist (loopback, metadata IP, DNS-rebind shape); header stripping.
- **Left open (§15):** destination-scoped rate limiting / coalescing /
  runaway-loop guard — note it, don't build the full scheme without real
  trigger-volume numbers; a basic runaway-loop guard is in scope, tuned
  thresholds are not.

**As built (ADR-0013):** all four hardenings live in `utils/webhook_security.py`,
applied by `_execute_webhook`. The SSRF guard resolves the host and rejects if
**any** resolved IP is non-routable (blocklist, not allowlist — organisers point
at arbitrary Slack/Discord/custom endpoints), unwraps IPv4-mapped IPv6, refuses
an unresolvable host, and keeps `follow_redirects=False`. Escaping + defang
apply to a new optional **`body_template`** (`{field}` placeholders; a
templateless webhook keeps sending the structured event as `json=`, which is
serialisation-safe). The cascade-depth guard from Phase 1 is the "basic
runaway-loop guard"; destination rate-limiting and the resolve→connect TOCTOU
(no connection pinning) are the two residual gaps, both recorded in ADR-0013 and
§15. Backend-only, no migration, not browser-observable — covered by unit tests
(`test_webhook_security.py` + template/header cases in `test_automations.py`).

## Phase 3 — Visual rule builder UI (§5.5) — ✅ DONE

Built **after** the JSON model is stable (§5.5's own guidance) — the schema is
what tests and any future plugins depend on, so it settles first.

- Node-based **Trigger → Conditions → Actions** builder (full spec, per owner
  decision) on the wired **Admin → Automations** page, visible only when the
  module is enabled for the competition. Condition/action editors are generated
  from the trigger's payload shape + the action catalog, so a new action type is
  additive.
- A lighter **personal-rules** surface for judges/team captains (their own
  `owner_user_id` rules) without the admin automation permissions.
- Tests (vitest): builder serializes to/from the Phase-1 JSON model; catalog
  gating; the module-disabled empty state.

**As built:** the builder is **catalog-driven** — the Phase-1 `/catalog`
endpoint grew from a bare list into `utils/automation_catalog.py` (triggers +
their payload fields, operators with a `unary` flag, actions with config-field
descriptors keyed by UI `kind`); a backend drift test asserts every executor has
descriptors and vice versa. The node-flow lives on the competition-scoped
`/automations` page (not Admin — that page hosts the **global** rules), which
also gained the **personal-rules** section (notify-self, any user). Serialization
is the pure `lib/automation-builder.ts` (`blankRule`/`toRuleInput`/`fromRule`),
unit-tested for the number/list/keyvalue coercion + unary-operator + round-trip
cases. Config `id` fields (hint/challenge) are text inputs for now — entity
pickers are a later polish. Frontend green +7 vitest; verified live: built a
`notify` rule through the UI (optional fields correctly dropped), it persisted
and re-opened for edit intact.

## Phase 4 — Feedback / Survey (#22, optional module) — ✅ DONE

Post-competition surveys as an **optional system module** `feedback` (§11.3),
now that the automation engine exists to consume its trigger.

- **Model + migration.** `Survey` (competition-scoped) + `SurveyQuestion`
  (types: `rating_1_10`, `rating_1_5`, `short_text`, `long_text`,
  `multiple_choice` with options) + `SurveyResponse` / `SurveyAnswer`. Full
  admin **editor** (build/reorder questions), competitor submission (one
  response per user/team per survey).
- **Event + trigger.** Emit **`feedback.submitted`** (already in §3.2) — which,
  because Phase 1 landed, is now a live **automation trigger**, satisfying
  #22's "as well as a trigger" without extra wiring.
- **CSV export** endpoint for responses (competition-scoped, permission-gated).
- **RBAC.** Add feedback permissions to §7.1 first (e.g. a **new "Feedback"
  category**: `feedback_manage`, `feedback_view_responses`) — none exist yet.
- `use-feedback.ts` hook (already anticipated in §8). Wire the survey builder +
  a competitor-facing "post-competition survey" surface.
- Tests: editor CRUD, each question type, one-response invariant, scoping/RBAC,
  the event fires and triggers a rule, CSV shape.

**As built:** `feedback` is the **second optional module** (so it now shares the
per-competition toggle surface with `automations`, and its routes 404 when
disabled). Responses are **per-user** (feedback is an individual opinion — even
in team mode), and a competition may hold **multiple** surveys. Three §7.1
Feedback perms (`feedback_manage`/`feedback_view_responses`/`feedback_submit`);
Judge gets all three, Participant gets `feedback_submit`. The `feedback.submitted`
payload carries `survey_id`/`response_id` (added to the catalog's trigger
fields). Frontend: a new gated **Feedback** nav item → `/feedback` with the
staff survey builder (question CRUD + reorder + open/close), the competitor
response form (rating chips / radio / text controls per type), a results dialog
(rating histograms, choice tallies, text lists) and CSV download; `use-feedback.ts`.
Verified live: built a 3-question survey, three competitors answered, the
`feedback.submitted` rule notified a submitter, and results + CSV matched.

**Post-Phase-4 automation glue (owner ask):** three additions wire feedback to
automations end to end. (1) Marking a survey open now emits **`survey.opened`**
(a trigger). (2) A new **`open_survey`** action (§5.3) marks a survey open from a
rule (tenant-guarded, idempotent, emits `survey.opened`). (3) The **first
time-based trigger, `competition.time_remaining`** — a per-minute scheduler
(`utils/automation_scheduler.py`, lifespan-started, `run_rule` factored out of
the engine) fires a competition-scoped rule **once** when `minutes_remaining`
first crosses its threshold condition (dedup via `trigger_count`; global time
rules skipped to avoid per-competition dedup). Together they express "an hour
before the competition ends, open the post-event survey, which notifies
participants" — verified end to end in tests. All catalog-driven, so the builder
shows the new trigger/action with no frontend change; no migration.

## Phase 5 — Challenge & Team analytics (#23) — ✅ DONE

Read-only reporting off data Tier 1 already captures (§13.2 logs *every* attempt,
success or fail) — no new instrumentation, just surfacing it.

- Aggregates: per-challenge solve count, completion rate, average solve time,
  attempt/fail volume; **team analytics** (progress, solve timeline). Served by
  a `dashboard`/analytics read module, competition-scoped.
- **RBAC.** `view_competition_analytics` / `view_global_analytics` already exist
  in §7.1 — enforce them (global one is the only cross-`competition_id` read
  path allowed, §6.3, for a global organiser).
- Frontend: an **Analytics** page + a couple of registered dashboard widgets
  (they slot into the Tier-2 widget registry). `use-analytics.ts` hook.
- Tests: aggregate correctness off a seeded submission set, scoping (a
  competition analytic never leaks another competition's data), RBAC.

**As built:** the `analytics` **optional module** (the third, after automations
and feedback — per-competition toggleable, 404 when disabled), `utils/analytics.py`
+ `routers/analytics.py` gated on `view_competition_analytics` (staff). Two
endpoints: `/analytics/challenges` (per-challenge solves, attempts/fails,
completion rate, average solve time — from `competition.start_at` — plus hints
used and linked ticket count) and `/analytics/teams` (per-subject rank / net
points / distinct-solve count / **first-blood count** / **tickets opened** /
last solve, reusing `compute_scoreboard`; first blood = earliest awarded
submission per challenge).
Timestamp math is done in Python for SQLite/Postgres portability. No migration
(pure read model). Frontend: the wired `/analytics` page (overview strip +
per-challenge and competitors/teams tables), `use-analytics.ts`; the placeholder
`ANALYTICS` data is gone. **Deviations:** `view_global_analytics` (cross-site
rollup) stays unbuilt — cross-competition consolidation is deferred (§6.3); a
global Administrator already reads any single competition's analytics via
`view_competition_analytics`. Skipped adding *new* dashboard widgets — the Tier-2
`challenge-health` widget already covers the at-a-glance case, so this is a
dedicated page rather than duplicating it.

## Phase 6 — Dashboard drag-and-drop (#26, §10.2–10.5)

Additive to the Tier-2 Phase-1 widget registry — which was built size-declaring
and self-contained *precisely* so this layer is additive, not a rewrite (§10.1).

- **Persistence.** `dashboard_layout(user_id, dashboard_key, layout_json)`
  (§10.3), per-user, saved explicitly on exit-edit — not per drag.
- **Grid + edit mode.** Fixed-column grid (§10.2); edit mode with drag handles,
  a **size-cycle** control stepping each widget through its declared legitimate
  sizes, collision reflow (engine resolves, iOS-home-screen style), and explicit
  save / cancel / **reset-to-default** (§10.4–10.5). Reuses the presence
  `mode: 'edit' | 'view'` convention (§10.4).
- **RBAC.** `customize_dashboard` / `manage_dashboard_widgets` already exist
  (§7.1) — enforce them.
- Tests: layout round-trip, collision reflow, size-cycle bounds, reset-to-default
  discards the saved layout, default fallback when none saved.

## Phase 7 — Collaborative rich-text / CRDT editing (#27, §4.2) — full spec

The biggest infra lift: Y.js as the CRDT layer under the existing TipTap editor,
replacing last-write-wins on **prose** fields only (titles/flags/points stay
plain form submits, §4.2). Both sides in this tier.

- **Infra.** Add `yjs` + `@tiptap/extension-collaboration` (TipTap/StarterKit
  already present) and a Y.js **sync backend**: a `notes/<resource_type>/<id>`
  WS room type reusing the §4.1 room + Tier-2 presence/soft-lock, relaying Y
  updates and **persisting** the doc (Postgres blob or MinIO). Likely a new
  **ADR-0013 (CRDT transport + persistence)**.
- **Staff-facing (§4.2):** challenge writeups, internal review notes, ticket
  internal notes.
- **Team-facing (§4.2):** per-challenge **team scratchpad**, scoped **strictly**
  to the owning team (no cross-team visibility), explicitly **not** a
  platform-provided hint channel — storage for the team's own thinking only.
  Read/write permission checked per request the same as any resource; the CRDT
  machinery stays agnostic to which side it's serving.
- **Soft-lock banner** when someone else holds `mode: 'edit'` (presence already
  carries `mode`, Tier-2 Phase 3).
- Tests: two-client convergence (concurrent edits merge, no lost writes), team
  isolation (a team can't read another's scratchpad), permission gating, presence
  soft-lock. Note SQLite/Postgres blob-storage parity (ADR-0006).

## Phase 8 — Onboarding / empty states (#24)

Cross-cutting UI, best done once the surfaces it decorates are finished.

- First-run experience: a brand-new competition with no challenges, empty
  scoreboard, empty dashboard, no tickets/surveys yet — guided next-step empty
  states instead of blank panels. No backend beyond what exists.
- Tests: empty-state rendering per surface (vitest).

## Phase 9 — Accessibility, responsiveness & optimization pass (#28)

Last, over finished surfaces — a polish pass, not a feature.

- Keyboard navigation across interactive surfaces (dialogs, the automation
  builder, the dashboard edit mode, the survey editor); focus management; visible
  focus rings.
- **Contrast** audit against the theming tokens (every shipped palette must hold
  AA — ties back to §9's legibility guarantee).
- **Mobile** layout for the competitor-facing screens in particular
  (scoreboard/challenges — people check standings from phones); the responsive
  drawer already exists, verify it end to end.
- A performance/optimization pass (bundle, query N+1s, WS reconnect behaviour
  under load).

---

## Cross-cutting notes

- **New ADRs expected:** ADR-0012 (event-dispatch async/outbox — resolves the
  ADR-0009 open question), ADR-0013 (CRDT transport + persistence), and possibly
  a short one for the webhook egress/SSRF policy. Write the ADR in the same phase
  as the decision, don't backfill.
- **New events (add to §3.2 first):** `automation.rule_triggered` already
  exists; `feedback.submitted` already exists. The automation *actions* likely
  introduce **`score.adjusted`** (`update_score`) and **`achievement.awarded`**
  (`award_achievement`) — add them before the executors emit them.
- **RBAC additions to §7.1 (add before enforcing):** flip the three reserved
  `automation_*` perms (Phase 1, + maybe `automation_delete`); a **new Feedback
  category** (`feedback_manage`, `feedback_view_responses`, Phase 4). Analytics
  and dashboard perms already exist — Phases 5–6 only *enforce* them.
- **§11.3 milestone:** automation (Phase 1) and feedback (Phase 4) are the
  **first genuinely optional, per-competition-toggleable modules** — the first
  real exercise of the module enable/disable + manifest-dependency mechanism the
  loader has carried unused since Tier 0. Get the dependency-refusal path right
  here.
- **Net-new infra flagged (don't let it hide inside a phase):** async
  dispatch/outbox (P0), per-user WS room + notifications table (P0), SMTP mailer
  + achievement store (P1), Y.js sync backend + doc persistence (P7). Everything
  else reuses existing infrastructure.
- **Still deferred past Tier 3** (unchanged): AI assistants (§12), SSO/LDAP/SAML
  (§7.7), the plugin *marketplace* + third-party sandboxing (§11, §15),
  multi-competition consolidation views (§6.3). The per-competition/white-label
  theming variant (ADR-0011) also stays deferred.

## Verification (per phase + at the end)

1. `cd backend && .venv/bin/pytest` and `cd frontend && npx vitest run` green;
   `npx tsc --noEmit` and `npx eslint .` clean.
2. Migrations apply cleanly up **and** down; native dev servers still start
   (restart — not `--reload` — the backend after any migration or new
   `plugins/<x>/` module, per the dev note).
3. End-to-end smoke on the running stack: create an automation rule (visual
   builder) that fires an in-app `notify` + a hardened `webhook` on
   `challenge.solved`, land a solve, watch both fire live; disable the
   automation module for a competition and confirm the rule stops; build a
   post-competition survey, submit it, see `feedback.submitted` trigger a rule
   and the CSV export; open the analytics page against seeded solves; drag +
   resize dashboard widgets, save, reload, confirm persistence + reset;
   two clients co-edit a challenge writeup and a team scratchpad with a soft-lock
   banner; walk the competitor screens on a mobile viewport.

## Out of scope (deferred past Tier 3)

- AI administrator/competitor assistants (§12); SSO/LDAP/SAML (§7.7); the plugin
  marketplace listing + third-party isolation/sandboxing (§11, §15);
  multi-competition consolidation/rollup views + global-organiser role (§6.3);
  per-competition / white-label theming (ADR-0011).
- Automation webhook **rate-limiting/coalescing** at production tuning (§15) —
  only a basic runaway-loop guard is in Tier 3; destination-scoped throttling
  waits on real trigger-volume numbers.
- Email/push as *delivery channels beyond* the automation `send_email` action
  (e.g. a full templated notification-preferences center) — the action ships;
  the channel-management surface does not.
