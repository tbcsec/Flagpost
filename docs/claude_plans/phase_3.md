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

## Phase 6 — Dashboard drag-and-drop (#26, §10.2–10.5) — ✅ DONE

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

**As built:** the `DashboardLayout` model (`dashboard_layouts`, per-user, keyed
`(user_id, dashboard_key)`; *not* competition-scoped — a personal preference,
same layout whichever competition it's viewed under, so the competition in the
route only scopes the `customize_dashboard` check) + a migration. Three
endpoints on the existing required-core `dashboard` module —
`GET/PUT/DELETE .../dashboard/layout?dashboard_key=` gated on
`customize_dashboard`: GET returns the saved layout or **null** (fall back to
the code default), PUT upserts on exit-edit, DELETE is reset-to-default (drops
the row). The layout JSON is **opaque to the backend** — the frontend registry
owns the widget catalog and legitimate sizes, so a new widget stays a
frontend-only change; the backend does light shape/bound validation only (known
`dashboard_key` allowlist, positive grid units, ≤50 entries). Frontend:
`lib/dashboard/layout.ts` (pure `mergeLayout`/`cycleSize`/`toSaved`/`moveEntry`,
unit-tested — snaps stale sizes back into the legitimate set, drops uninstalled
widgets, appends newly-registered ones), a `DashboardGrid` component with the
edit mode (native HTML5 drag-and-drop — no DnD library; per-widget size-cycle +
show/hide; Save/Cancel/Reset toolbar), and `use-dashboard.ts` layout hooks.
Managers (who hold `customize_dashboard`) customize the `manager` dashboard;
participants keep the fixed default (§10 scope). **Deviations:** the grid is an
**ordered flow** of column-spanned widgets (CSS grid reflow) rather than a 2D
`{row,col}` engine — reorder + size-cycle + show/hide over the 4-col grid, which
covers §10.2–10.5's intent without a free-form positioning layer; row-spans stay
declared metadata (widgets keep natural height, no content clipping). Only the
`manager` dashboard is customizable this tier (participant/team/organiser keys
are forward-compatible but unbuilt). `manage_dashboard_widgets` stays
Administrator-only and unused (it governs the widget *catalog* — marketplace
territory, deferred). No event emitted (personal preference, like the theme
palette override).

## Phase 7 — Collaborative rich-text / CRDT editing (#27, §4.2) — ✅ DONE

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

**As built:** the required-core **`collab` module**. Owner placement (this
tier's ask): **team scratchpad** in the challenge dialog, **staff notes** in the
ticket thread — those two of the §4.2 surfaces (challenge writeups / review notes
are additive later, same machinery). One `note/<doc_key>` WS room carries both;
`doc_key` = `team_challenge:<team_id>:<challenge_id>` or `ticket:<ticket_id>`,
and `utils/collab.resolve_note` authorizes per request (team membership; or
`ticket_view_internal_notes` staff — **not** the opener, so the staff channel
stays invisible to competitors). **Transport = dumb relay + client-snapshot
persistence (ADR-0014)** — the server relays opaque Y.js update frames
(`broadcast(exclude=sender)`) and stores one full-state blob per doc
(`collab_documents` + migration), never decoding the CRDT; base64 over the JSON
socket. The §4.1 router gained an `on_message` hook (broadcast-only rooms
unchanged). Frontend: `yjs` + `@tiptap/extension-collaboration`, `lib/collab.ts`
(Y.Doc ↔ socket binding), `lib/ws.ts` `send()` buffering, and a `<CollabNote>`
component. **Deviations from the sketch:** the room path is `note/<doc_key>`
(single path segment — the §4.1 router is `/<type>/<id>`) rather than
`notes/<resource_type>/<id>`; persistence is a **Postgres/SQLite `LargeBinary`
blob** in `collab_documents`, not MinIO (one small row per note, cascades with
the competition — §6.2); the ADR is **0014** (0013 was already webhook
hardening). The **soft-lock/"who's here" cue reuses the existing challenge/ticket
presence indicators** (which already carry `mode`, Tier-2 Phase 3) instead of a
new per-note presence set + banner; **per-cursor awareness is not built** (out of
scope for two prose fields). Two-client convergence is proven by a Y.js
round-trip unit test (frontend) + a server relay/isolation test (backend); a
webpack alias pins Y.js to one instance (its singleton requirement). Tests:
backend +7 (`test_collab.py`: team isolation, ticket staff-only/opener-rejected,
null→persisted snapshot, live relay w/o self-echo, per-doc isolation, unknown
scope), frontend +4 (base64 round-trip, two-doc convergence, snapshot rebuild).

## Phase 8 — Onboarding / empty states (#24) — ✅ DONE

Cross-cutting UI, best done once the surfaces it decorates are finished.

- First-run experience: a brand-new competition with no challenges, empty
  scoreboard, empty dashboard, no tickets/surveys yet — guided next-step empty
  states instead of blank panels. No backend beyond what exists.
- Tests: empty-state rendering per surface (vitest).

**As built:** a reusable **`EmptyState`** primitive (`components/ui/empty-state.tsx`
— token-styled framed panel: icon bubble + title + next-step copy + optional
action, with a few shared inline-SVG glyphs) applied **role-aware** across the
first-run surfaces: **challenges** (staff → "Create a challenge" CTA into manage
mode; competitor → "check back when the organisers publish"), **scoreboard**
("No scores yet — first flag takes the top spot"), **support** (competitor → a
"Need a hand?" panel with the New-ticket CTA; staff → "you'll get a cue when one
lands"), **feedback** (staff → "Create a survey" CTA; competitor → "when the
organisers open one"). Plus a **manager `FirstRunGuide`** on the dashboard — a
3-step "Getting started" card (create challenges / invite teams / brand the
event) that fetches the same dashboard stats the widgets do and **disappears once
the first challenge is published**. No backend. Tests: `EmptyState` rendering
(vitest, +2). *(Bundled in the same commit: a design tweak — dialog widths +25%
across the board, base `max-w-lg`→`max-w-[40rem]` (512→640px) and the two
override tiers scaled to match, so the collaborative notes sections get more
room; the `<CollabNote>` editor min-height also bumped `min-h-24`→`min-h-32`.)*

## Phase 9 — Ad-hoc: pre-release features & cleanup (owner-driven)

An owner-inserted phase (added 2026-07-23) for a set of features and cleanup
items wanted for the **initial public release** that weren't scoped into the
roadmap earlier. Items range from small to large and are added here as the owner
specifies them — each one gets designed, built, and documented across **all**
the docs (ARCHITECTURE / ROADMAP / this plan / CLAUDE / UI-INTEGRATION-NOTES, plus
an ADR when it's a real decision) as it lands. Unlike the other phases, this one
is **one push at the end** (not per-item) — the owner signals when the set is
complete; work accumulates until then.

Items (this list grows as the owner adds them):

- **Individual-mode Participants page** ✅ — the `/participants` page rendered a
  "no endpoint yet" placeholder in individual mode (team mode was already wired
  via `TeamPanel`). Now backed by a real roster: `GET
  /api/competitions/{id}/participants` (`routers/participants.py`, mounted by the
  `competitions` module) lists every competition-scoped Participant-role holder
  (§7.5) with join time, distinct-solve count, and standing (rank/points reused
  from `compute_scoreboard` so ranking matches the board exactly); gated on
  `challenge_view`, scoped by `competition_id`. Frontend: `use-participants.ts` +
  a `ParticipantsPanel` (a "your standing" summary + the competitors roster,
  self-row highlighted) wired into the page. No migration; no new event (pure
  read). Tests: backend +4 (`test_participants.py` — roster+standing, RBAC,
  competition scoping, 404).
- **Module management (per-competition)** ✅ — the admin surface for the
  per-competition module toggle *backend* (which already existed, Tier 3 Phase 1).
  `GET /api/competitions/{id}/modules` now returns the **full inventory** (added
  `required_core` to `ModuleStateOut` + a `all_manifests()` loader accessor) —
  required-core modules locked "always on", optional ones with their
  per-competition enabled state; gated on `edit_competition`, "Core" (locked) /
  "Optional" (toggleable) split. Frontend: `use-modules.ts` + `modulesApi` + a
  `ModulesPanel`; the dead `PLUGINS` placeholder is removed. **Owner decisions:**
  (1) module scoping stays **per-competition** (§11.3 — multi-tenant, one install
  runs competitions with different feature sets), *not* site-wide; (2) because
  it's competition-scoped, the UI **lives on Competition Settings**, not the
  global Admin section — the standalone `/admin/plugins` page + its Admin-nav
  entry were removed and `ModulesPanel` mounts under Settings with the
  competition's other config. And **disabled modules now drop from the nav**: a
  member-readable `GET /modules/enabled` (`challenge_view`, returns enabled
  optional-module ids — unlike the `edit_competition` management list, so it gates
  *competitors'* nav too) drives a `module` tag on the `COMP_NAV` items
  (Feedback/Analytics/Automations); a disabled module's item is filtered out. The
  toggle shares the `["modules", competitionId]` query key, so disabling a module
  removes its nav entry live. Tests: module-toggle test updated for the new shape
  + a core-module inventory assertion + `test_enabled_modules_endpoint_is_member_readable`.
- **Admin → Users page** ✅ — was a placeholder; now the full account directory +
  lifecycle. New `users` required-core module + `routers/users.py` (`/api/users`):
  list/search (`view_all_users`), create, edit (incl. password reset), soft-ban/
  unban, hard-delete (all `manage_users`). Soft-ban = new `User.is_active`
  (+ migration) enforced at `auth/deps.get_current_user` (a banned user's live
  access token is rejected), at login (403), and at refresh; a ban + a password
  reset both **revoke the user's refresh sessions**. Two lockout guards (mirroring
  the roles router): can't ban/delete **yourself** or the **last active
  Administrator**. New §3.2 events `user.created/updated/banned/unbanned/deleted`
  (added to the event catalog *and* the automation catalog — they're admin-only
  automation triggers governed by `manage_users`, keeping the drift test green).
  The directory shows the platform-wide distinction only (holds the global
  Administrator role or not); per-competition role assignment stays on Admin →
  Roles. Frontend: `usersApi` + admin hooks in `use-users.ts`, a wired page
  (search / create+edit dialogs / ban / delete-confirm, self-row protected), and
  a `UserFormDialog`; the `DIRECTORY_USERS` placeholder is removed. Tests: backend
  +7 (`test_users.py` — directory+search, RBAC, create+login, edit+password,
  ban-blocks-login-and-token+unban, self/last-admin guards, delete+guards).
- **Name references instead of raw IDs** ✅ — admins/judges no longer paste long
  team/user ids. A reusable `EntityCombobox` (`components/ui/entity-combobox.tsx`,
  dependency-free filter-as-you-type dropdown that **displays a name but stores
  the id**) replaces the raw-id inputs: the **event-log** filters (Admin → Event
  log) — "Actor" from the global user directory (`useUsers`), "Team" from the
  selected competition's teams (`useTeams`, enabled once a competition is picked);
  and the **automation rule-builder condition values** — a `team_id` field →
  team picker, a `*user_id` field → participant picker, scoped to the rule's
  competition (a new optional `competitionId` prop threaded into `RuleBuilder`;
  global rules keep the plain input). No backend change. `subject_id` (mode-
  dependent) stays a plain input for now.
- **Cleanup: React hydration warning** ✅ — the no-flash theme script rewrites
  `<html>`'s palette/mode/accent before hydration, so the SSR defaults never
  matched the client's first paint (a `data-palette` mismatch warning on every
  load with a non-default cached theme). Fixed with `suppressHydrationWarning` on
  the root `<html>` (`app/layout.tsx`) — the standard pattern for a pre-hydration
  theme script.
- **Clone a competition** ✅ — an admin turns a configured "baseline" competition
  into fresh near-identical ones. `POST /api/competitions/{id}/clone` (body
  `{name}`, gated on `create_competition`) → `utils/competition_clone.py` deep-
  copies the **config** into a new competition (regenerated ids, remapped
  cross-references, new invite code, **schedule cleared**): settings
  (description/mode/visibility), categories, challenges (incl. the stored flag,
  so it still solves), hints, **file attachments** (the stored objects are
  duplicated — added `ObjectStorage.get`), **feedback surveys + questions** (as a
  closed template), and the per-competition **module on/off** state. Deliberately
  **not** copied (clean slate): participants/teams/roles, submissions/scores/
  adjustments/achievements, hint reveals, tickets, announcements, notifications,
  survey *responses*, automation rules, audit log. Emits `competition.created`
  (with `cloned_from`). Frontend: `competitionsApi.clone` + `useCloneCompetition`
  + a **Clone** action per row on Admin → Competitions opening a **name-prompt**
  dialog (pre-fills "`<name>` (copy)", editable — so no "Test / Test-1 / Test-2"
  pile-up). Owner scope: attachments + surveys included, automation rules
  excluded. Tests: backend +6 (`test_clone.py` — config+clean-slate, cloned flag
  still solves, attachment object duplicated, surveys cloned closed, no
  participants/solves carried, RBAC/404).
- **Cleanup: flaky-suite hardening** ✅ — surfaced while adding clone tests (more
  `competition.created` events). Fire-and-forget background handlers (ADR-0012 —
  the automation engine) could outlive their test and run against the *next*
  test's freshly-recreated schema, flaking unrelated automation/feedback tests
  non-deterministically (identical code passed 293 one run, failed 21 another).
  Fixed in the test harness: `conftest._create_schema` now drains
  `event_bus.wait_for_background()` before `drop_all`, so no background task
  leaks across the per-test schema boundary. Suite is deterministic again.
- **Admin → Competitions: archive + delete** ✅ — the placeholder Archive/Delete
  buttons are now wired. **Archive** (`POST /competitions/{id}/archive` +
  `/unarchive`, `edit_competition`) = a reversible soft-close: new
  `Competition.archived_at` (+ migration), retained but **hidden from the topbar
  switcher and the lobby** (the active selection stays visible even if just
  archived) and badged in the admin list. **Delete** (`DELETE /competitions/{id}`,
  the existing `delete_competition` perm) hard-removes the competition and its
  whole tenant tree (§6.2 FK cascade), behind a confirm dialog. New §3.2 events
  `competition.archived/unarchived/deleted` (event + automation catalogs;
  archive→`edit_competition`, delete→`delete_competition` triggers). Frontend:
  `archive_at` on the `Competition` type, `useArchiveCompetition`/
  `useDeleteCompetition`, the wired admin page (archive toggle, delete confirm,
  Archived badge) + switcher/lobby filtering. Tests: backend +5
  (`test_competitions.py` — archive/unarchive+events, RBAC, delete+event, RBAC, 404).
- **Admin → Dashboard (site overview)** ✅ — was a placeholder; now the real
  cross-competition oversight view for a global admin. `GET /api/admin/overview`
  (`routers/admin_overview.py`, mounted by the `dashboard` module) gated on
  **`view_global_analytics`** — the §6.3 cross-competition permission that had no
  consumer until now. Returns platform totals (accounts active/total, competitions
  active/archived, teams, challenges published/total, submissions, solves) plus a
  **per-competition health** row for every competition: derived status
  (draft/scheduled/running/ended/archived — Python date math for SQLite/Postgres
  parity), participants (teams or Participant-role users by mode), published
  challenges, solves, open tickets. Pure read model, no migration. Frontend:
  `use-admin-overview.ts` + the wired page (six total tiles + a health table with
  status badges, open-ticket counts highlighted). The whole
  `lib/placeholder-data.ts` file is **deleted** — its last consumers
  (`MODULE_STATUS`, `DIRECTORY_USERS`, …) are all wired now. Tests: backend +3
  (`test_admin_overview.py` — totals+health, status derivation incl. archived, RBAC).
- **Admin → Site settings (operational)** ✅ — was a placeholder; now the two
  operational (non-theming) site configs that belong there today. **Registration
  policy**: a new `SiteSettings.registration_open` (+ migration) — when closed,
  `POST /register` returns 403 (only admins mint accounts via Admin → Users); the
  public `GET /site-settings` now carries `registration_open` so the login page
  hides the Register link and `/register` shows a "closed" notice. **SMTP config**:
  `smtp_host/port/username/password/from/starttls` on `SiteSettings`, editable via
  `GET`/`PUT /site-settings/operational` (`manage_site_settings`; the password is
  **write-only** — never serialized, GET returns `smtp_password_set`). The
  `send_email` action's mailer now resolves SMTP from the **DB** (falling back to
  the env config, then a logged no-op) — so email is admin-configurable, no env
  redeploy. AI config stays deferred (a disabled note). Frontend: operational
  types/api/`use-site-settings` hooks + the wired page (registration select + SMTP
  form) + register/login handling. Tests: backend +3 (`test_site_settings.py` —
  operational RBAC, SMTP password write-only round-trip, closing registration
  blocks signup; the two public-shape assertions updated for `registration_open`).
- **Branded favicon** ✅ — there was no favicon. Added `app/icon.svg` (Next.js
  auto-serves it as `<link rel="icon">`): the Flagpost mark — green flag on a
  light post — on a dark brand tile, matching the sidebar lockup.
- **Cleanup: nested `<form>` on the challenge editor** ✅ — `ChallengeForm`
  rendered `AttachmentsSection` + `HintsSection` (each with its own `<form>`)
  *inside* the challenge `<form>`, which is invalid HTML (a hydration warning).
  Restructured so those sub-sections and the action buttons sit as **siblings**
  of the challenge form (not children); the submit button lives outside it and
  submits via a `form={useId()}` attribute, preserving the fields → sub-sections
  → actions layout. No behaviour change.
- **Expanded branding — custom logo + mandatory attribution** ✅ — orgs could
  already set the platform name + palette + accent; this adds a **custom logo**
  while keeping Flagpost visible as the underlying project. Owner call (via
  question): the platform-name wordmark beside the logo is an **admin toggle**
  (`show_wordmark`) — on for icon-only marks, off for logos that bake in the name.
  - *Storage.* The logo lives **in the DB**, not object storage: a `deferred`
    `logo_data` `LargeBinary` on the `SiteSettings` singleton (+ `logo_content_type`
    / `logo_updated_at`), migration `b4c5d6e7f8a9`. Rationale: branding must render
    **pre-auth** (login/register) and on the **infra-free** SQLite/preview stack,
    where MinIO isn't reachable — same reasoning as the collab snapshot blob
    (ADR-0014). The bytes are `deferred` so the frequently-read (and public)
    settings row never loads them; only the streaming endpoint undefers.
  - *API.* Public `GET /site-settings` gains `logo_url` (a
    `/api/site-settings/logo?v=<epoch>` path from a model property that reads only
    non-deferred columns) + `show_wordmark`. `manage_site_settings`-gated
    `POST`/`DELETE /site-settings/logo` store/clear the logo (1 MB cap; PNG, JPEG,
    WebP, GIF, SVG). The **public** `GET /site-settings/logo` undefers + streams the
    bytes with `X-Content-Type-Options: nosniff` and a `Content-Security-Policy:
    default-src 'none'; … sandbox` — so a **directly-opened SVG logo can't execute
    script** (the app renders it via `<img>`, which already disables SVG scripting;
    the header covers the pasted-URL case). `show_wordmark` rides the existing
    appearance `PUT`. All reuse `site.settings_updated` — no new event.
  - *Frontend.* `Lockup` gained `logoUrl` + `showWordmark` (custom `<img>` swaps in
    for the mark; wordmark optional) across the sidebar, login and register. The
    site-settings query **absolutizes** `logo_url` to the API origin (`apiAssetUrl`)
    in a `select`, since `<img src>` resolves against the frontend host otherwise.
    `useUploadLogo` / `useDeleteLogo`; a Logo section on Admin → Appearance (preview,
    upload/replace/remove, the wordmark checkbox).
  - *Attribution.* A **mandatory, non-configurable** `PoweredByFooter` — "Powered by
    Flagpost" with the built-in mark, linking to the GitHub repo — renders on every
    page (app shell + the public auth screens). This is the controlled part of the
    rebrand: the logo/name/palette are the org's, but Flagpost stays credited.

- **Username-primary identity, optional email** ✅ (ADR-0015) — email was a
  required, sole login identifier; that's awkward for a CTF (competitors without
  an email, organisers bulk-creating handles). Owner calls (via question): reuse
  the **display name as the username** (not a separate field), **case-insensitive**.
  - *Model / migration `c5d6e7f8a9b0`.* `User.email` → nullable (unique when
    present; multiple NULLs OK on SQLite + Postgres). Display name gains a
    **case-insensitive unique** functional index `lower(display_name)`.
  - *Auth.* `auth/identity.py` centralises the case-insensitive lookups
    (`find_by_identifier` — email then display name, deterministic;
    `display_name_taken`/`email_taken`), shared by register + admin create/edit.
    `LoginRequest.identifier` accepts the display name **or** email (with an `email`
    JSON alias for back-compat). Register/admin-create enforce display-name
    uniqueness (409) and only check email when supplied. Admin → Roles assign
    resolves by **email or username** so email-less accounts stay assignable.
    `UserOut`/`UserAccountOut`/`AssignmentOut.user_email` nullable.
  - *Frontend.* Login field "Username or email" (`identifier`); register + admin
    user dialog make email optional and relabel the name field "Username" with a
    "must be unique" hint; `.email` render sites null-guarded (users table shows
    "—", toasts/roles/actor-combobox use the display name). Edit can set/replace an
    email but not clear one yet (blank = unchanged).
  - *Tests.* New auth-flow + users tests (no-email register, login by username,
    case-insensitive uniqueness + login, identifier alias); fixed-literal display
    names in helpers made unique.

- **Platform export / import** ✅ (ADR-0016) — a full-fidelity, section-selectable
  backup on Admin → Site settings. Owner calls (via questions): **config + live
  data** (a true backup, not just setup) and **additive "skip existing"** import.
  - *Engine.* `utils/backup.py` avoids hand-coding ~25 entities with a **generic
    serialiser** (every column; datetimes→ISO, `LargeBinary`→base64, deferred cols
    `undefer`-ed on export) + a declared `SPECS` registry per table (FK-remaps,
    import order, natural key, competition-owned flag). Adding a table to backups
    is then one line — and completeness is auditable (no silently-forgotten table,
    which in a backup tool is a data-loss trap).
  - *Document.* One versioned JSON (`schema_version`), keyed by table under `data`,
    carrying the selected `sections`: `site_settings`, `users`, `roles`,
    `competitions`, `automations`, `audit_log`.
  - *Additive import.* Top-level entities skip by natural key (user by name/email,
    role/competition by name, assignment by (user,role,competition), rule by
    (name,trigger,competition,owner), audit by id). A **competition is atomic** —
    if its name exists the whole owned subtree is skipped (no merged/duplicate
    challenges); cross-cutting collections (assignments, rules) stay additive
    per-row. New ids minted, FKs rewritten via id maps (required miss → skip row,
    optional → null), invite codes regenerated.
  - *Security.* Full fidelity **incl. secrets** (password/flag hashes, SMTP) so a
    restore actually works — the file is sensitive (UI says so) and both endpoints
    are `manage_site_settings`-gated. Excluded: `refresh_sessions` +
    transient `notifications`/`collab_documents`/`dashboard_layouts`. New
    non-triggerable `platform.imported` audit event.
  - *API + UI.* `POST /site-settings/export` (JSON file download) / `import`
    (per-table created/skipped) / `GET .../backup/sections`. `BackupPanel` +
    `use-site-settings` hooks; export = section checkboxes → download, import =
    file picker → section checkboxes → additive result summary.
  - *Tests.* `test_backup.py` — round-trip fidelity, additive skip, restore after
    delete (fresh ids, solve re-linked to the still-present user), section
    selection, foreign-document rejection, endpoint auth gate.

- **Multiple-choice challenges + competition-wide guess limit** ✅ (§13.2) — a
  third `flag_type` where the author gives a set of options and marks one correct.
  - *Storage/grading.* `challenges.choices` (JSON, **public** — the options shown
    to competitors) + the correct option **hashed in `flag_hash`** like a static
    flag (never serialized). The competitor submits the option they picked; it's
    graded server-side by the same hash path. `has_flag` for MC needs both a hash
    and choices; publishing still requires it.
  - *Guess cap.* A finite option set is trivially brute-forced, so
    `Competition.mc_guess_limit` (null = unlimited, owner call: **competition-wide,
    not per-challenge**, set in competition settings) caps guesses per subject per
    MC challenge. `submit_flag` refuses further guesses **before grading** once the
    cap is hit (so the block can't be probed for correctness) and returns
    `attempts_remaining`; the challenge list/detail expose it too
    (`subject_attempt_count[s]`). Migration `d6e7f8a9b0c1`.
  - *Reach.* Clone (`choices` + `mc_guess_limit`) and the generic backup carry the
    new columns automatically.
  - *Frontend.* Challenge editor: a "Multiple choice" flag type + an options editor
    (add/remove rows, a radio marks the correct one; on edit the correct radio
    starts blank since the answer isn't returned — re-pick to change it). Challenge
    dialog: radios + "N guesses remaining" + a "used all your guesses" locked
    state. Competition settings: the guess-limit input.
  - *Tests.* `test_multiple_choice.py` — options shown/answer hidden, the cap
    blocks a 3rd guess (even the correct one), a fresh subject still gets its own
    allotment, correct-within-limit solves, and validation (≥2 unique options,
    answer among them).

## Phase 10 — Accessibility, responsiveness & optimization pass (#28)

Last, over finished surfaces — a polish pass, not a feature. (Was Phase 9;
renumbered when the ad-hoc Phase 9 was inserted.)

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
  ADR-0009 open question), a CRDT transport + persistence ADR, and possibly
  a short one for the webhook egress/SSRF policy. Write the ADR in the same phase
  as the decision, don't backfill. *(As shipped: ADR-0012 event-dispatch,
  ADR-0013 webhook egress hardening, ADR-0014 CRDT transport — the webhook one
  took 0013, so CRDT landed at 0014.)*
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
