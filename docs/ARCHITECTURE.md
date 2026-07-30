# Architecture

This document describes the technical architecture of the platform: how the
system is structured, the core patterns that recur across features, and the
reasoning behind them. It complements `VISION.md` — where that document says
*what* and *why*, this document says *how*.

It is a living reference. As modules are built, update this file rather than
letting the code drift away from it.

---

## 1. Guiding Architectural Principles

These follow directly from the vision document's core principles, translated
into concrete technical commitments:

1. **Everything is an event.** No feature should mutate state silently. Every
   meaningful change in the system is emitted as a named event that other
   parts of the system (automations, notifications, analytics, plugins,
   audit log) can react to independently.
2. **Kernel, required-core, and modules are distinct tiers, not a flat
   core-vs-plugin split.** A small kernel (auth, tenancy, event bus) is
   never optional. A required-core feature set (challenges, scoring,
   hints, tickets, announcements, dashboard) makes the platform usable as
   a CTF tool at all, and isn't user-toggleable even though it's built the
   same way as everything else. Beyond that, functionality — integrations,
   extra notification channels, niche automation actions, AI assistants —
   ships as an optional module, in the box or from the marketplace later.
   See §11.3 for the full model.
3. **Real-time by default, not bolted on.** Anywhere multiple people look at
   the same resource at the same time (a challenge, a support ticket, a
   scoreboard), the UI should reflect that live, not on refresh.
4. **One data-access module per domain.** Each entity (challenges, teams,
   tickets, hints, automations…) gets its own hook/query module. Components
   never talk to the API client directly.
5. **The design system is tokens, not components.** Visual identity (color,
   radius, density) lives in CSS custom properties, not hardcoded Tailwind
   classes, so a competition can be reskinned without touching component
   code.
6. **Permissions are data, checked in one place.** Roles and their
   permission sets live in the database (§7), and every route enforces
   them through a single shared dependency rather than ad hoc role checks
   scattered through handlers. Changing what a role can do is a data
   change, never a code change.

---

## 2. Technology Stack

| Layer | Choice | Notes |
|---|---|---|
| Frontend framework | Next.js (App Router), React, TypeScript | |
| Styling | Tailwind CSS v4 + shadcn/ui | `@theme` token layer, see §9 |
| Server state | TanStack Query | one hook module per domain, see §8 |
| Client state | Zustand | auth, active-competition context, UI prefs |
| Real-time transport | WebSockets (native), Y.js for collaborative text | see §4 |
| Rich text | TipTap | challenge writeups, judge notes, tickets |
| Backend framework | FastAPI (async) | |
| ORM / migrations | SQLAlchemy 2.x / Alembic | |
| Database | PostgreSQL | |
| Cache / pub-sub transport | Redis | |
| Object storage | MinIO (S3-compatible) | challenge files, evidence, avatars |
| Deployment | Docker Compose (default), Kubernetes (future) | |

`VISION.md` suggests Next.js 14 / React 18 specifically; this table
deliberately doesn't repeat those numbers. Frontend framework versions
move fast enough that hardcoding a specific major version in a reference
doc just goes stale — build against latest stable Next.js/React/TypeScript
at implementation time rather than treating `VISION.md`'s suggestion as a
version pin. Where a specific version *does* matter architecturally
(Tailwind v4's `@theme` directive is load-bearing for §9, SQLAlchemy 2.x's
async API is load-bearing for the FastAPI integration), the table calls it
out explicitly; everywhere else, "latest stable" is the actual intent.

---

## 3. Event-Driven Core

### 3.1 The Event Bus

At the center of the backend sits a lightweight async pub/sub event bus.
Core code emits events; automations, plugins, notifications, and the audit
log all subscribe independently. Core code never needs to know who's
listening.

```python
event_bus = EventBus()

@event_bus.on("challenge.solved")
async def handle_solve(event: dict):
    ...

await event_bus.emit("challenge.solved", {
    "challenge_id": ...,
    "team_id": ...,
    "competition_id": ...,
    "user_id": ...,
    "is_first_blood": ...,
})
```

Key properties:

- **Wildcard subscriptions.** A handler can subscribe to `challenge.*` to
  catch every challenge-related event without enumerating them.
- **Per-plugin ownership.** Handlers registered by a plugin are tagged with
  that plugin's id. When a plugin is disabled, its handlers stop firing
  immediately — no re-subscription required, no orphaned listeners.
- **Isolated failure.** Handlers run concurrently and a failure in one
  handler is logged, not allowed to break the others or the request that
  triggered the event.
- **No blocking on emit.** Emitting an event never blocks the request that
  triggered it beyond dispatch; slow handlers (e.g. an outbound webhook)
  don't hold up the API response.

### 3.2 Canonical Event Vocabulary

Event names are `<entity>.<verb>`, past tense, e.g.:

```
competition.created         competition.updated        competition.started
competition.ended           competition.member_joined  competition.time_remaining
competition.archived        competition.unarchived     competition.deleted
competition.rules_accepted
team.created                team.member_joined         team.member_left
team.deleted
challenge.created           challenge.updated          challenge.published
challenge.deleted           challenge.solved           challenge.attempted
challenge.guesses_reset     challenge.rated            challenge.hint_requested
hint.released
category.created            category.deleted
user.registered              user.password_changed
user.email_verified
user.created                 user.updated               user.banned
user.unbanned                user.deleted
role.created                 role.updated               role.deleted
role.assigned                role.unassigned
api_token.created            api_token.revoked
ticket.created               ticket.assigned            ticket.resolved
ticket.message_posted
survey.submitted             survey.opened
announcement.published
site.settings_updated
score.adjusted               achievement.awarded
scoreboard.frozen            scoreboard.unfrozen
module.enabled               module.disabled
automation.rule_triggered    automation.rule_created
automation.rule_updated      automation.rule_deleted
platform.imported
```

`site.settings_updated` is site-wide (not competition-scoped), so its payload
carries no `competition_id` — the audit log records it with a null tenant,
which is correct for a global setting change. The same is true of an
`automation.rule_*` event for a **global** rule (`competition_id = None`,
§5.1).

`challenge.attempted` fires on every **graded** flag submission, right or
wrong (§13.2 logs a row per attempt; this is that rule's event half — refusals
before grading, like the rate limit or the MC guess cap, emit nothing). It's
what keeps attempt-counting surfaces (dashboard stats, challenge health,
analytics) live, and its automation trigger is gated
`view_competition_analytics` — others' attempts are staff analytics data, not
member-visible play state. Volume is bounded by the submission rate limit.

`score.adjusted` and `achievement.awarded` are the automation engine's
mutating-action events (§5.3 `update_score` / `create_award`) — an
automation's side effects are events like any other mutation's.
`achievement.awarded` also fires for a **manual** judge award (same record).
`scoreboard.frozen` / `scoreboard.unfrozen` record a scoreboard freeze/unfreeze
(§13) — both a staff action and an automation action. `platform.imported` is a
**platform-administration** event (a backup import, ADR-0016): like the
`automation.*` family, `platform.*` events are site-wide (null tenant) and
**excluded from automation triggers** — they are not competition events, so
nothing automates on them (`TRIGGERABLE_EVENTS` in `event_catalog.py` drops both
prefixes). `module.enabled` / `module.disabled` record the per-competition
optional-module toggle (§11.3); the canonical vocabulary above is mirrored in
code by `backend/utils/event_catalog.py`, which is also what validates an
automation rule's `trigger_type` (§5.1).

This vocabulary is the single source of truth for what "things happen" in
the system — it should be documented and versioned alongside the schema, not
left implicit in code. New event types are additive; existing ones should
not change shape without a migration note.

### 3.3 Who Consumes Events

```
                 ┌──────────────┐
  core mutation ─▶  event_bus   │
                 └──────┬───────┘
        ┌───────────────┼───────────────┬───────────────┐
        ▼               ▼               ▼               ▼
   audit log      automation engine  notifications     plugins
```

---

## 4. Real-Time Layer

### 4.1 Presence & Live Updates

Any page showing a shared resource (a challenge, a ticket, the judge
dashboard, a live scoreboard) opens a scoped WebSocket connection:

```
wss://<host>/ws/<resource_type>/<resource_id>
```

Design decisions:

- **Auth token is sent as the first message after connect, never as a URL
  query parameter.** URL-embedded tokens leak into proxy logs, browser
  history, and the `Referer` header; a first-frame auth handshake avoids
  that entire class of leak. The server gives the client a short window to
  send the auth frame before closing the connection.
- **Exponential backoff reconnect** (capped, with jitter) so a dropped
  connection doesn't hammer the server on reconnect storms.
- **Debounced presence clearing.** When a connection drops, the "who's
  here" list isn't cleared instantly — a short grace period absorbs blips
  from brief reconnects so the UI doesn't flicker.
- **Presence payload is minimal**: id, display name, avatar, role, and an
  optional `mode` (`view` / `edit`) so other clients can show a soft-lock
  banner when someone else is actively editing the same resource.

Two room idioms coexist, chosen per surface:

- **Snapshot rooms** (scoreboard, announcements) push the full shared state —
  right when everyone in the room sees the same thing.
- **Ping rooms** (tickets, and the per-competition **activity room**
  `activity/<competition_id>`) push tiny id-only frames and let each client
  refetch its own permission-filtered REST slice — required when the surface
  is per-user (solved state, unlock chains, role-scoped stats), because a
  shared snapshot can't exist. The activity room is the generic instance: the
  competitions module fans out a **curated allowlist** of §3.2 events as
  `{type: "activity", event}` frames (never payload bodies), and the frontend
  maps event names to query invalidations (`lib/live.ts`) behind one
  shell-level socket, throttled per query key so bursts collapse. Ticket and
  announcement events stay off the allowlist — they have their own
  tighter-scoped rooms. Adding a live surface is a map entry, not a new room.

### 4.2 Collaborative Editing

Long-form text fields that multiple people may edit concurrently use Y.js as
the CRDT layer under TipTap, rather than last-write-wins saves. Simple
fields (titles, flags, point values) stay as ordinary form submissions —
CRDTs are reserved for prose, not the whole record.

This applies on both sides of the platform, using the same mechanism:

- **Staff-facing**: challenge writeups, internal review notes, ticket
  internal notes.
- **Team-facing**: per-challenge scratchpad notes shared by a team, so
  teammates can collaboratively work a challenge together in real time
  rather than coordinating over an external chat app. This is the same
  `<resource_type>/<resource_id>` room model from §4.1, just scoped to a
  team's own challenge-notes resource instead of a staff-only one — the
  presence/soft-lock/CRDT machinery doesn't need to know or care which side
  of the platform is using it, only that the resource's read/write
  permissions are checked per request the same as any other resource.
- **Competitor-facing**: the same per-challenge scratchpad for a competitor
  with no team (individual-mode play), private to that one user. It keeps the
  CRDT transport rather than degrading to a plain textarea, so a solo
  competitor's own tabs and devices stay in sync — "collaborative" editing
  with a single author is still multi-client editing.

Team-facing notes must be scoped strictly to the owning team — no cross-team
visibility — and, unlike staff notes, should never be treated as an implicit
solve-path hint channel: they're storage for the team's own thinking, not a
platform-provided collaboration feature that leaks structure the team hasn't
already worked out itself.

> **Status (Tier 3 Phase 7):** shipped as the required-core `collab` module. A
> single `note/<doc_key>` WS room carries every side; `doc_key` encodes the
> resource (`team_challenge:<team_id>:<challenge_id>`,
> `user_challenge:<user_id>:<challenge_id>`, or `ticket:<ticket_id>`) and
> `utils/collab.resolve_note` decides read/write per request — team membership
> for a team scratchpad, **own-user plus `challenge_view`** for a personal one
> (#46: not staff, not teammates), `ticket_view_internal_notes` (staff, **not**
> the opener) for a ticket note. The transport is a **dumb relay** with client-side
> snapshot persistence (**ADR-0014**): the server relays opaque Y.js update
> frames and stores one full-state blob per doc (`collab_documents`), never
> decoding the CRDT. Frontend: `<CollabNote>` (TipTap + `@tiptap/extension-collaboration`
> over a Y.Doc) wired into the challenge dialog (team scratchpad, or the personal
> one when the competitor has no team) and the ticket thread (staff notes). The
> soft-lock/"who's here" cue rides the existing
> challenge/ticket presence indicators (§4.1); per-cursor awareness is not built.

### 4.3 What Should Be Real-Time on This Platform

- Live scoreboard during a running competition
- Judge dashboard: active competitors, recent solves, support queue
- Support ticket threads (competitor ↔ judge)
- Challenge review/approval workflow (multiple organisers editing one
  challenge draft)
- Announcements banner

**Announcement severity & audience.** An announcement carries a `severity`
(`info` / `warning` / `critical`) and an audience: the whole competition, or a
chosen set of teams/users. Two rules follow from targeting:

- **Read is filtered** — a targeted announcement is simply absent from the list
  for anyone outside its audience. Staff who can post see every announcement
  (their own sent history).
- **Targeted announcements never touch the shared room.** The
  `announcements/<competition_id>` room fans a frame to *every* connected
  member, so broadcasting a targeted one there would leak the body to the whole
  competition while merely *looking* targeted. Whole-competition announcements
  keep that cheap shared broadcast; targeted ones are delivered per-recipient
  over their `/ws/user/<id>` room instead. The join snapshot is filtered the
  same way, so a reconnect can't reveal what the live path withheld. Audience
  resolution lives in one place (`utils/announcements`) so read and delivery
  can't drift.

### 4.4 In-App Notifications

Baseline notification delivery is **in-app only**: a notification center
(bell icon) with per-user read/unread state for all events, plus an audio
cue that's scoped **exclusively to the Support Ticket module**: a new
ticket cues staff (admins/judges), and a reply cues whichever side didn't
just post — staff replying cues the participant, a participant replying
cues assigned staff. No other event, including first blood or
announcements, plays a sound; everything else is visual-only via the bell.
This exists independently of the automation engine's `notify` action
(§5.3): Support Tickets is required-core (§11.3), so competitors and
judges need a way to notice ticket activity before automations exist, not
after.

Notifications ride the same WebSocket infrastructure as the rest of this
layer, but over a per-user room (`/ws/user/<user_id>`) rather than the
per-resource rooms in §4.1, since a notification isn't scoped to one
resource the way presence is. **As built** (Tier 3 Phase 0): the in-app
bell + per-user read/unread state is real (a required-core `notifications`
module), and email delivery arrived as promised as the automation
`send_email` action (§5.3, Tier 3 Phase 1) rather than a second notification
system — SMTP is env-configured and the action no-ops when it's unset.
Per-user **preferences** are now built (Tier 3 Phase 9): `User.notification_prefs`
holds in-app category mutes (`inapp_tickets` / `inapp_automations` /
`inapp_announcements`, enforced in `create_notifications` so every producer
respects them) plus client-honored `browser` / `sound` delivery hints,
read/written at `/api/notifications/preferences`.

Posting an announcement (§4.3) also creates a bell notification per recipient —
the banner auto-dismisses, so without one an announcement could be missed
entirely by looking away. There is exactly **one sanctioned override** of a
category mute: a **`critical`** announcement is delivered even when
`inapp_announcements` is off (`create_notifications(..., force=True)`), because
the operator is saying something the competition can't afford to miss. It
overrides the *in-app* mute only — `browser` and `sound` stay opt-in, since
those need an OS permission grant and forcing audio on someone is hostile. Any
new use of `force` is a product decision, not a convenience.
Per-user **email** delivery stays deferred (email is automation-rule-driven,
not a per-user channel); *push* (service-worker) delivery stays deferred too.

---

## 5. Automation Engine

### 5.1 Data Model

A rule is a flat `Trigger → Conditions → Actions` record:

```python
class AutomationRule:
    id: str
    name: str
    trigger_type: str            # a §3.2 event name, e.g. "challenge.solved"
    conditions: list[Condition]  # [{field, operator, value}, ...]
    actions: list[Action]        # [{type, ...config}, ...]
    is_enabled: bool
    competition_id: str | None   # None = global rule
    owner_user_id: str | None    # None = org rule, else personal rule
    trigger_count: int
    last_triggered_at: datetime | None
```

- **Triggers are the §3.2 vocabulary, verbatim.** `trigger_type` is a
  canonical event name (`challenge.solved`), not a parallel enum — validated
  against `utils/event_catalog.py`, so anything that emits an event is
  automatable with zero per-feature wiring, and a new event type is a new
  trigger for free. The `automation.*` events themselves are **not**
  triggerable (the trivial self-loop).
- **Trigger authorization.** A trigger is *not* a free choice: each event maps
  to the permission that governs observing it (`utils/automation_catalog.py`
  `TRIGGER_PERMISSIONS` — role/user/site events need the global admin
  permission, staff events a staff competition permission, member-visible
  events `challenge_view`). Creating or editing an **org** rule checks the
  creator holds that permission in the rule's scope, and the `/catalog` trigger
  list is filtered the same way — so a Judge can't automate on (and exfiltrate)
  `role.assigned` in their competition. **Personal** rules need no such check:
  they only ever fire for events the owner *caused*, so they can't surface data
  the owner didn't already act on.
- **Scoping**: a rule with `competition_id = None` fires across every
  competition; scoping to one competition is the common case for
  organiser-authored rules. Creating/editing a competition's rules takes
  `automation_create`/`automation_edit` on that competition; a **global**
  rule requires holding those permissions via a global assignment
  (Administrator), since it fires everywhere.
- **Ownership**: `owner_user_id = None` means an org-wide rule; a non-null
  value scopes the rule to fire only for events caused by that user, and
  lets that user manage the rule without needing elevated automation
  permissions. This is what lets individual judges or team captains set up
  personal notification rules without an admin doing it for them. Because
  they're creatable without automation permissions, **personal rules are
  restricted to the `notify` action targeting the owner** — a personal rule
  is a saved search that pings you, never a way to run privileged actions
  (`update_score`, `webhook`, …) without holding the permissions an org rule
  requires.

### 5.2 Evaluation

The engine is invoked from the same place events are emitted: on every
`event_bus.emit(...)`, load enabled rules matching `trigger_type`, evaluate
`conditions` against the event payload, and execute `actions` for every rule
that matches. This keeps the automation engine a *consumer* of the event
bus rather than a parallel system — anything that emits an event is
automatically automatable, with no extra wiring per feature.

As built (Tier 3 Phase 1): the engine subscribes on the **background lane**
(ADR-0012), so evaluation and actions never hold up the request that emitted
the event; conditions are AND-ed (`equals`, `not_equals`, `contains`,
`gt`/`gte`/`lt`/`lte`, `exists`/`not_exists`); every fire updates
`trigger_count`/`last_triggered_at` and emits `automation.rule_triggered`.
Two loop guards: `automation.*` events are never evaluated as triggers, and a
**cascade-depth cap** stops a chain of rules whose actions' events trigger
further rules (the fuller runaway detection stays open in §15). If the
automations module is disabled for the event's competition (§11.3), nothing
fires for that event — global rules included.

**One trigger is time-based, not event-based** (`competition.time_remaining`):
a rule can fire "N minutes before a competition ends", which has no mutation to
hang an event off. A periodic scheduler (`utils/automation_scheduler.py`,
started by the lifespan alongside the audit consumer) ticks each minute,
computes each competition's `minutes_remaining`, and fires matching
competition-scoped rules through the same `run_rule` path — **once**, when the
rule's threshold condition (`minutes_remaining <= 60`, say) first goes true
(dedup via `trigger_count`). This pairs naturally with the `open_survey` action:
"an hour before the end, open the post-event survey" → `survey.opened` → "notify
participants". Global time rules are skipped (they'd need per-competition dedup).

### 5.3 Action Types (initial set)

| Action | Notes |
|---|---|
| `notify` | in-app notification to a user, team, or role |
| `send_email` | templated, uses the event payload for interpolation |
| `webhook` | outbound HTTP call, see hardening below |
| `release_hint` | unlocks a hint for a team/competitor |
| `unlock_challenge` | e.g. unlock a bonus challenge on first blood |
| `create_award` | grant a titled award (title/description) that also carries scoreboard points |
| `create_ticket` | e.g. auto-flag a challenge with high fail rate |
| `update_score` | bonus/penalty adjustments |
| `open_survey` | mark a feedback survey open for responses (emits `survey.opened`) |
| `freeze_scoreboard` / `unfreeze_scoreboard` | control the public board's freeze (emits `scoreboard.frozen`/`unfrozen`) — e.g. freeze on `competition.ended` |
| `create_announcement` | post an announcement to the competition (emits `announcement.published`) |

### 5.4 Webhook Action Hardening

Because webhook targets, headers, and body templates are admin-authored but
the **values substituted into them** (challenge names, team names, ticket
titles) are user-authored, the webhook action needs the same treatment a
public-facing template engine would:

- Validate the outbound URL against an SSRF blocklist (no internal/loopback
  targets) before every call, not just at rule-creation time.
- Strip caller-uncontrollable headers (`Authorization`, `Cookie`, `Host`,
  `X-Forwarded-*`) from admin-defined header sets so a rule can't be used to
  forge origin or smuggle credentials.
- Escape substituted values for the declared `Content-Type` (JSON string
  escaping for JSON bodies, etc.) so a team name containing quote characters
  can't break out of its field and inject sibling JSON keys.
- Defang chat-platform rendering tokens (broadcast/mention/channel tokens,
  markdown-style links) in substituted values before they reach a
  Slack/Discord/Teams webhook, so a competitor can't rename their team to a
  broadcast token and trigger a mass-ping through an organiser's
  notification rule.

This matters more on a competition platform than most SaaS products: team
and challenge names are adversarial input by design.

**As built (Tier 3 Phase 2, ADR-0013):** all four land in
`utils/webhook_security.py`. The SSRF guard resolves the host and rejects if
**any** resolved IP is non-routable (loopback/private/link-local — incl. the
`169.254.169.254` metadata endpoint — reserved/multicast/unspecified; IPv4-mapped
IPv6 unwrapped), refuses an unresolvable host, and the caller keeps redirects
off. Escaping + defang apply to a webhook's optional `body_template` (where an
admin composes a message with `{field}` placeholders); a templateless webhook
sends the structured event as `json=`, which needs no escaping. Two residual
gaps are called out in ADR-0013 and §15: the resolve-then-connect TOCTOU (no
connection pinning yet) and destination rate-limiting.

### 5.5 Suggested Frontend: Visual Rule Builder

A node-based Trigger → Condition → Action builder (rather than a form) pays
off once there are more than a couple of action types. Treat this as a v2
addition once the JSON model above is stable — don't build the visual layer
before the schema, since the schema is what plugins and tests actually
depend on.

**As built (Tier 3 Phase 3):** a numbered node-flow (When → If → Then) editor,
**generated from a catalog endpoint** (`GET /api/automations/catalog`) rather
than hand-coded per action — `utils/automation_catalog.py` describes each
trigger's payload fields, each operator (with a `unary` flag), and each action
type's config fields (with a UI `kind`), so adding an action is a backend-only
change the builder picks up (a drift test keeps the descriptors and the executor
registry in lockstep). Builder-state↔JSON serialization is a pure, unit-tested
module (`lib/automation-builder.ts`). The same builder serves org rules
(competition-scoped and, on Admin → Automations, global) and the lighter
**personal-rule** surface (notify-self only, §5.1); the `notify` target options
are filtered by context (personal → self; org → everyone but self).

---

## 6. Multi-Competition Tenancy

A single deployment should be able to host many competitions at once,
fully segregated from each other, rather than requiring one deployment per
competition.

### 6.1 Motivating Use Case

Globally distributed events are the clearest driver: a multi-site
competition where each physical site currently needs its own separate
scoreboard instance should instead be able to run as one deployment, with
each site modeled as its own competition. Sites stay fully segregated from
each other's data (challenges, teams, scores, tickets) while still being
consolidatable — a global admin view spanning sites for cross-site
standings or reporting — without organisers having to stand up and
maintain a separate instance per location.

### 6.2 Isolation Model

Segregation is enforced at the **application level**, not via
per-competition database schemas:

- Every tenant-scoped table carries a `competition_id` foreign key.
- Every query and router enforces `competition_id` scoping consistently —
  this is a cross-cutting concern checked at the data-access layer (§8),
  not something left to individual endpoints to remember.
- The event bus (§3) and automation engine (§5) already carry
  `competition_id` on their payloads/rules, so tenancy scoping is additive
  to work already done, not a parallel system.

App-level scoping is the deliberate choice over schema-per-competition
isolation: a genuinely isolated-schema-per-competition model would make
cross-site rollups (the whole point of this feature) harder, not easier,
since it would require fan-out queries across schemas instead of a single
filtered query.

### 6.3 Cross-Competition Views

A small set of views are explicitly allowed to read across the
`competition_id` boundary, for roles with the appropriate permission
(e.g. a global event organiser, not a site-level judge):

- Cross-site standings / aggregate scoreboard
- Cross-site challenge-health comparison (which challenges are
  under-performing at which sites)
- Org-wide automation rules (already modeled via `competition_id = None`
  in §5.1)

These are additive read paths on top of the per-competition data, not a
relaxation of the isolation model — a competitor or site-level judge should
never be able to see another site's data through them.

### 6.4 Status

This is a direction, not yet a finalized design — worth revisiting once the
first concrete cross-site reporting requirement is in hand, since that
requirement will shape exactly which cross-competition views are needed.

---

## 7. RBAC: Roles & Permissions

### 7.1 Permission Model

Permissions are granular, named capabilities (`challenge_edit`,
`ticket_assign`, `manage_users`), not baked-in role checks. Every
permission belongs to exactly one **category**, used purely for organizing
the admin UI into sections rather than a long flat checklist:

```
Competition Management   create_competition, edit_competition,
                          delete_competition, manage_schedule
Challenges                challenge_view, challenge_create, challenge_edit,
                          challenge_delete, challenge_publish
Scoring                   score_override, scoreboard_freeze
Teams                     team_view_all, team_edit_any, team_disqualify
Support Tickets           ticket_view, ticket_respond, ticket_assign,
                          ticket_view_internal_notes
Announcements             announcement_create, announcement_delete
Feedback                  feedback_manage, feedback_view_responses,
                          feedback_submit
Users & Roles             manage_users, manage_roles, view_all_users,
                          manage_api_tokens  (minting/revoking personal API
                          tokens, issue #75 — a token's own holder can still
                          view/revoke it without this, §7.7)
Site Settings             manage_site_settings  (global — the site-wide
                          theme/branding an administrator sets, §9)
Analytics                 view_competition_analytics, view_global_analytics
Dashboard                 customize_dashboard, manage_dashboard_widgets
Automations               automation_view, automation_create,
                          automation_edit  (enforced since the automation
                          engine shipped, Tier 3 — personal rules need none
                          of these, §5.1)
Audit                     view_audit_log
```

Each permission also carries a **scope**: `global` (site-wide — creating a
competition, managing users) or `competition` (meaningful only within one
competition — editing a challenge, responding to a ticket). This mirrors
the `competition_id` model from §6: a competition-scoped permission is only
ever evaluated against a specific competition, never site-wide, and a
global permission is never granted per-competition.

### 7.2 Roles Are Data, Not Code

Roles are rows in the database, not a hardcoded enum, so new roles can be
created and existing ones fine-tuned without a code change or deploy:

```python
class Role:
    id: str
    name: str
    description: str
    is_system: bool          # True for the three built-in roles (7.3)
    scope: Literal["global", "competition"]
    permissions: list[str]   # permission keys from 7.1
```

A role's `permissions` list is just an array of permission keys — the
categorized admin UI (7.1) is what turns editing that array into checkboxes
grouped by section instead of a raw JSON editor.

### 7.3 Built-In Default Roles

Three roles are seeded at install time and cover the common case without
any setup:

| Role | Scope | Summary |
|---|---|---|
| **Administrator** | global | Every permission. Manages users, roles, and every competition. |
| **Judge** | competition | Full operational control *within an assigned competition*: challenges, scoring, tickets, announcements, analytics. No user/role management, no cross-competition visibility. |
| **Participant** | competition | Competitor-facing permissions only: view challenges, submit flags, manage own team, create support tickets, view the scoreboard. |

These three are marked `is_system = true`: they can't be deleted, and their
permission sets can't be edited directly, so "a Judge can always run their
own competition" stays a safe assumption to build other features on. An
admin who wants a variant — e.g. a Judge who can't override scores — clones
the built-in role into a new, fully editable custom role rather than
mutating the original.

Because the catalog (7.1) is the source of truth for what a system role can
do, the three built-ins are **re-synced from their specs on every startup**
(`seed_system_roles`), not just inserted once at migration time. That's what
lets a permission *added to the catalog after* an install was first migrated —
a new module's keys, say — reach that install's built-in roles without a
hand-written data migration. Custom roles (and any non-system role) are never
touched by the sync.

### 7.4 Custom Roles

Beyond the three defaults, admins can create additional roles from
scratch or by cloning an existing one (system or custom), then check/uncheck
individual permissions from the categorized list in 7.1. Typical custom
roles on a real competition: "Co-organiser" (Judge permissions plus
`manage_schedule`), "Read-Only Observer" (view-only across every category),
"Challenge Author" (challenge permissions only, no ticket or scoring
access). Custom roles default to `scope: competition` unless explicitly
created as global, since almost everything below Administrator is
naturally competition-scoped.

The admin surface for this (the `roles` required-core module, gated on
`manage_roles`) is a small API + editor with a few operational invariants worth
stating, since other features rely on them:

- **System roles are read-only** — edit/delete is refused; you clone to vary
  one (mirrors the `is_system` guarantee in 7.3).
- **An assignment's scope must match its role** — a global role is assigned
  site-wide (`competition_id = None`), a competition role to one competition.
- **A role can't be deleted while it's still assigned** — so deleting one never
  silently strips access mid-competition; unassign first.
- **The last Administrator can't be unassigned** — an install always keeps at
  least one account that can manage roles, so it can't lock itself out.
- A competition-scoped role's editor only offers competition-scoped permissions
  (a global permission held via a per-competition assignment never grants, so
  offering it would only mislead). Every role mutation emits its §3.2 event.

### 7.5 Assignment & Scoping

A user's role is assigned per competition, not globally, except for the
`global`-scoped Administrator role:

```python
class RoleAssignment:
    user_id: str
    competition_id: str | None   # None only valid for global-scope roles
    role_id: str
```

This is what lets the same account be a Judge on one competition and a
plain Participant (or nothing at all) on another — important for the
multi-site case in §6, where a site's judges shouldn't automatically gain
judge-level access to every other site's competition just because they
hold a judge role somewhere.

### 7.6 Enforcement

Permission checks happen at the data-access layer, not scattered across
individual route handlers — the same principle §6.2 applies to
`competition_id` scoping applies here:

```python
@require_permission("ticket_respond")
async def respond_to_ticket(ticket_id: str, ..., current_user: User = Depends(get_current_user)):
    ...
```

`require_permission` resolves the user's role for the request's
`competition_id` (or the global role, for global-scoped permissions),
checks the permission is in that role's set, and 403s otherwise. Because
this is one shared dependency rather than per-endpoint role lists, adding a
new permission or changing what a role can do never requires touching
route code — only the role's stored `permissions` array.

### 7.7 Authentication Mechanism

RBAC needs a resolved, trustworthy `current_user` before any permission
check means anything — that identity comes from a JWT access token,
short-lived (e.g. 15 minutes) and paired with a longer-lived refresh
token issued at login and stored as an httpOnly cookie, not
`localStorage`, so it isn't readable by injected or third-party JS.

**Identity: the display name is the primary login identifier** (a username),
required and **case-insensitively unique** (a functional index on
`lower(display_name)`). **Email is optional** — a secondary handle, unique when
present. Local login accepts the **display name *or* the email** (matched
case-insensitively; email first, then display name, so the match is
deterministic). This keeps sign-up frictionless (no email required) and lets an
account exist without one; assigning roles still works for email-less accounts
because Admin → Roles resolves by display name or email (ADR-0015). SSO, when it
ships, still plugs into the same session contract below.

The same access token is reused for both transports rather than
maintaining two auth schemes:

- **REST**: standard `Authorization: Bearer <token>` header, verified by a
  FastAPI dependency that resolves `current_user` for downstream RBAC
  checks (§7.6).
- **WebSocket**: the same access token, sent as the first frame after
  connect per §4.1 — not a second, WS-specific token type. One issuance
  and refresh path to reason about, not two.

**Personal API tokens** (issue #75) are a deliberate, narrow exception: a
long-lived, `flp_`-prefixed opaque token for programmatic REST access without
capturing a browser session. It authenticates as its owner with that owner's
full effective permission set — no separate scope model — and is **REST only**,
never accepted at the WebSocket handshake. Only its SHA-256 hash is stored
(mirrors `RefreshSession`, and follows ADR-0020: hash what is only verified);
the raw value is shown once, at mint time.

Minting is **self-only**: a user creates a token for their own account from
`/profile`, and the create route has no holder field at all. This is a
structural property, not a check — since there is no way to express "a token
for someone else", no permission can become a route to impersonating another
account. `manage_api_tokens` is correspondingly an *oversight* grant: list
every token and revoke any of them, so a leaked credential can be killed by
somebody other than its holder. Revocation only removes access, so the
permission cannot be used to gain any.

Password auth is the baseline (hashed with a modern KDF, never reversible)
and the **only** authentication method for initial release — no SSO
module ships until after public launch. This isn't a technical
simplification so much as a scoping one: building the module contract
correctly matters more upfront than building multiple auth backends against
it. SSO (LDAP/SAML/OAuth) stays a **module**, not kernel, and is explicitly
deferred (see `ROADMAP.md`); when it does ship, it plugs into the same
"produces a `current_user` and a session" contract that password login
already established, so adding a provider later doesn't touch the RBAC
layer at all, only how the initial identity gets established. Getting that
contract right during the local-auth build is the actual prerequisite for
SSO being a clean bolt-on later rather than a refactor.

---

## 8. Data Access Pattern (Frontend)

Every domain gets exactly one hook module wrapping TanStack Query:

```
lib/hooks/
  use-challenges.ts
  use-teams.ts
  use-hints.ts
  use-support-tickets.ts
  use-feedback.ts
  use-automations.ts
  use-competitions.ts
  use-users.ts
```

Rules for these modules:

- Components never call the raw API client directly; they call a hook.
- Query keys are namespaced by domain and, where relevant, competition id,
  so cache invalidation can be scoped (`['challenges', competitionId]`) and
  switching the active competition doesn't need a full cache flush.
- Mutations invalidate their own domain's queries; cross-domain
  invalidation (e.g. solving a challenge should also invalidate the
  scoreboard) is explicit, not implicit — no silent global invalidation.
- Default `staleTime` should be short but non-zero (e.g. 60s) with
  `refetchOnWindowFocus` off, since real-time updates arrive over the
  WebSocket layer, not via polling.

This is the same discipline applied to state as §3 applies to events: one
place per concept, not scattered fetches.

---

## 9. Design System / Theming

Visual identity is a token layer, not a component library choice. Colors
are defined as CSS custom properties in HSL and consumed through Tailwind
v4's `@theme` directive:

```css
@theme {
  --color-primary: hsl(var(--primary));
  --color-background: hsl(var(--background));
  --color-card: hsl(var(--card));
  /* ... */
}
```

This makes a few features possible without touching component code:

- **Multiple built-in palettes**, switched by a `data-palette` attribute on
  `<html>`. As built (Tier 2 Phase 4) the shipped set is **Harbor** (dark,
  default), **Eclipse** (dark), **Umbra** (dark), **Daybreak** (light) and
  **Sandstone** (light) — each a full token set. Palettes are **curated
  presets, not a free-form background picker**: a palette is ~15 interdependent
  channels that have to hold AA text contrast, an elevation order, and a hue
  family at once, so hand-tuned presets are the only way to *guarantee*
  legibility. (A single arbitrary background hex would need a whole derivation
  engine + contrast clamp to be safe — deferred; presets are the deliberate
  scope.)
- **Accent color override**: one hue written **only** into `--primary` /
  `--ring` (+ an on-accent foreground chosen by YIQ perceived brightness),
  converted from a preset or a custom hex to HSL channels at runtime — the
  whole surface recolours without a rebuild or a forked stylesheet, while
  `--success` (brand green) and the logo are left untouched (LOGO-SPEC §7).
  Because an accent is one colour into a slot designed to be swapped, a fully
  custom hex is safe here in a way a custom background is not. The token layer
  supports scoping this per-organisation/per-competition, but the **current
  build scope is site-wide only** — one platform theme an administrator sets
  for the whole install (Admin → Appearance), persisted in a **site-settings
  singleton** and read publicly so login/register brand themselves before auth.
  A user may override just the *palette* for themselves (topbar menu, stored in
  `localStorage`); the accent and platform name stay site-wide. The
  per-competition / white-label variant is deferred and may return later if
  demand warrants (ADR-0011).
- **Custom logo (site-wide branding, Tier 3 Phase 9)**: an administrator may
  replace the built-in Flagpost mark with the organisation's own **logo** — a
  superset of the earlier "only the name is white-labelled" rule (this relaxes
  LOGO-SPEC §7). The logo image is stored **in the DB** on the site-settings
  singleton (a `deferred` blob, not object storage) so it renders **pre-auth**
  and on the infra-free stack, and served by a **public** streaming endpoint with
  `nosniff` + a `sandbox` CSP so a direct-navigation SVG can't execute script. An
  admin **`show_wordmark`** toggle hides the platform-name wordmark for logos that
  bake in the name. **Attribution is mandatory and not configurable**: a subtle
  "Powered by Flagpost" footer (built-in mark → the project's GitHub) renders on
  every page — an org may fully rebrand, but Flagpost stays visibly the
  underlying platform. Site-wide only, like the rest of theming (ADR-0011).
- **Palette mode** drives the `dark:` Tailwind custom variant
  (`@custom-variant dark`) via a `data-mode` attribute the shell mirrors from
  the active palette, rather than a class scattered through every component —
  so a new dark palette needn't be enumerated in the variant.

No flash on load: the resolved theme (palette + mode + any accent channels) is
cached in `localStorage`, and a tiny inline script in the document head applies
it before first paint; a `ThemeApplier` mounted above every page (public
included) then reconciles it with the live site-settings read.

Component library (shadcn/ui-style primitives) sits on top of this token
layer, not the other way around — components should reference
`bg-primary`, `text-muted-foreground`, etc., never a raw hex value.

---

## 10. Dashboard Customization

Users should be able to rearrange their own dashboard — reorder sections,
step widgets through a set of legitimate sizes, show/hide widgets — rather
than the layout being fixed in code. This is bounded customization, not a
free-form page builder (see §10.2). Initial scope is the
**administrator/judge dashboard** only; the same mechanism can extend to
other dashboards (team dashboard, per-competition organiser dashboard)
later without redesign, since nothing about the approach below is
judge-specific.

> **Status (Tier 3 Phase 6):** the widget-registration layer (§10.1) shipped
> in Tier 2 with a *fixed* layout; the customization layer described below is
> now built for the **manager** dashboard — per-user `dashboard_layouts`
> persistence (§10.3), an edit mode with drag-reorder, a size-cycle control,
> show/hide, and save / cancel / reset-to-default (§10.4–10.5), gated on
> `customize_dashboard`. Two simplifications from the spec below: the grid is an
> **ordered flow** of column-spanned widgets (CSS grid reflow) rather than a 2D
> `{row, col}` positioning engine, and row-spans stay declared metadata (widgets
> keep natural height); reorder + size-cycle + show/hide over the fixed-column
> grid deliver §10.2–10.5's intent without a free-form positioning layer. The
> layout JSON is opaque to the backend — the frontend registry owns the widget
> catalog and legitimate sizes, so a new widget is a frontend-only change.

### 10.1 Why This Has to Be an Architectural Decision, Not a Feature Bolted On Later

If dashboard sections are built as components hardcoded into a page layout
(`<StatsPanel />` above `<RecentSolves />` above `<TicketQueue />`, fixed in
JSX), retrofitting drag-and-drop later means rewriting every widget to be
repositionable. The fix is to never give a widget a static position in the
first place:

- Every dashboard section is registered as a **widget**: an id, a
  component reference, its set of legitimate sizes and a default
  position/size (§10.2), and (for plugin-provided widgets) the manifest
  entry from §11.1's `widgets` list — core and plugin widgets go through
  the identical registration path.
- The dashboard page itself renders a **grid container** plus whatever
  widget ids are in the current user's saved layout, in that layout's
  order, position, and size — it does not know or care what any
  individual widget contains.
- Widget components are self-contained: they fetch their own data via the
  domain hooks (§8) and render correctly at every size they declared as
  legitimate. A widget must not assume it's in a particular position or
  adjacent to a particular other widget.

### 10.2 Widget Sizing & Grid Model

Customization is bounded, not infinite — closer to how widgets work on a
phone home screen than a general-purpose page builder. There is no
free-form pixel resize.

- The dashboard is a fixed-column grid (e.g. a 4- or 6-column grid,
  decided once and shared by every widget).
- Each widget declares, in its registration (§10.1), a fixed set of
  **legitimate sizes** it supports in grid units — e.g. a stat-count widget
  might only support `1×1`, while a chart widget might support `2×1` and
  `2×2`. A widget never claims a size its own content can't render sensibly
  at.
- Positions snap to grid cells; a widget occupies a whole number of
  columns and rows, and the grid engine (not the user) resolves collisions
  by shifting other widgets, the same way iOS/Android home-screen icons
  reflow around a moved icon rather than allowing overlap.
- "Resizing" a widget means cycling it to the next size it declared as
  legitimate, not dragging a corner handle to an arbitrary dimension.

This keeps every widget layout describable as `{widget_id, size, position}`
with `size` drawn from a small enumerated set — deliberately constrained so
the grid stays legible and every widget always renders inside a size it was
actually designed for.

### 10.3 Layout Persistence

A user's dashboard layout (widget ids, grid position, size, visibility) is
stored per-user, not global — `dashboard_layout(user_id, dashboard_key,
layout_json)`, where `dashboard_key` distinguishes which dashboard this is
(`admin`, and later `team`, `organiser`, etc.). Saving is explicit ("Save
layout" / exit edit mode), not on every drag, to avoid a write per pixel of
movement.

### 10.4 Edit Mode

The dashboard has two states: normal (widgets render, no drag handles,
clicking inside a widget behaves normally) and edit mode (drag handles
appear for repositioning, a size-cycle control appears on each widget for
stepping through its legitimate sizes from §10.2, clicking is for
rearranging rather than interacting with widget content, and an explicit
save/cancel/reset-to-default appears). This mirrors the presence/soft-lock
`mode: 'edit' | 'view'` distinction already used in §4.1 — a UI convention
worth keeping consistent across the app rather than reinventing per
feature.

### 10.5 Defaults and Reset

Every `dashboard_key` ships a default layout (defined once, in code, as the
fallback used when a user has no saved layout yet). A "reset to default"
action in edit mode discards the user's saved layout rather than requiring
them to manually rebuild it — customization should be easy to back out of,
not just easy to do.

---

## 11. Plugin System

### 11.1 Manifest-Driven Loading

Each plugin is a directory with a manifest (`plugin.yaml`) declaring what it
provides, discovered and loaded at startup:

```yaml
id: example_plugin
name: Example Plugin
version: 1.0.0
provides:
  routes: true
  event_listeners: true
settings:
  - key: api_key
    type: secret
widgets:
  - id: example_widget
    label: Example Widget
nav_items:
  - label: Example
    path: /plugins/example
extensions:
  challenge.tabs:
    - component: example-tab
      label: Example
      required_permissions: [MANAGE_CHALLENGES]
```

The loader:

1. Scans the plugins directory for valid manifests.
2. Imports the module and calls a standard `setup(app, event_bus, db_factory)`
   entry point.
3. Mounts any FastAPI router the plugin provides, gated on the plugin's
   `enabled` flag being checked on every request, not just at mount time.

**As built** (Tier 3 Phase 1): the `automations` module is the first genuinely
*optional* one (`required_core: false`), so it's the first to exercise the
per-request enable gate — a loaded optional module always *mounts*, but its
per-competition state lives in the `competition_modules` table (absent row =
enabled) and is checked per request via `plugins.loader.is_module_enabled`
(`GET`/`PUT /api/competitions/{id}/modules`). Required-core modules skip the
gate (always on). Manifest `dependencies` are enforced at load (the loader
refuses a module whose dependency isn't present); `settings`/`widgets`/
`nav_items`/`extensions` from the manifest above remain declared-but-unused
until a module needs them.

### 11.2 Extension Slots

Rather than plugins patching arbitrary UI, the frontend defines named
**extension slots** (`challenge.tabs`, `dashboard.widgets`,
`team.detail.panels`, etc.). A plugin declares which slot(s) it wants to
render into, and a generated registry maps slot name → plugin component.
Core pages render a `<PluginSlot name="challenge.tabs" />` and don't need to
know what, if anything, is registered there. This keeps the extension
surface finite and reviewable instead of open-ended DOM patching.

### 11.3 Core Kernel vs. Modules

The flat "if disabling it wouldn't affect a competition, it's a plugin"
rule undersells how much of the platform can actually be built this way.
A more precise split has two parts: a small non-negotiable kernel, and
everything else as a **module** — a much broader category than "plugin"
implied, closer to how Obsidian treats nearly every visible feature as a
core plugin that happens to ship on by default, rather than a hardcoded
exception.

**The kernel** (never a module, never disableable): Auth & RBAC (§7), the
competition entity and tenancy scoping (§6), the event bus (§3), and the
module loader itself. These aren't features so much as what every module —
including the ones shipped in the box — is built on top of. No manifest,
no toggle; without them there's no platform to load anything into.

**A required core sits on top of the kernel**: Challenges, Scoring (and the
live scoreboard it drives), Hints, Support Tickets, Announcements, and
Dashboard customization (§10). With every optional module below disabled,
this is the floor — the platform should still operate as a fully
functional CTF competition tool, not a shell waiting for modules to make
it useful. These may still be *organized* internally as modules
(registered through the same path as everything else, for
code-organization consistency), but they don't carry an enabled/disabled
flag in the admin UI the way optional modules do.

**Everything beyond that is an optional module**: Feedback, the Challenge
Lifecycle/Review workflow, Analytics, Automations, AI Assistants, and any
third-party integration (LDAP/SSO providers beyond the default,
Slack/Discord notification channels, CTFtime import/export, scoreboard
embed widgets). These register through the identical manifest-driven path
in §11.1, whether they ship with the platform or come from the marketplace
later. Modules split by **provenance and trust**, not by capability:

- **System modules** ship with the platform, are reviewed and maintained
  alongside core code, and run in-process at the same trust level core
  code has today — the sandboxing question in §15 is a marketplace
  concern, not a system-module one. Most are enabled by default and can be
  disabled per competition — e.g. turning off the Feedback module for a
  competition that doesn't want a post-event survey uses the exact same
  mechanism as disabling a marketplace Slack-notification module, not a
  special case.
- **Marketplace modules** are third-party, opt-in from the start, and need
  the stronger isolation story flagged in §15 before that ships.

`VISION.md`'s Plugin Ecosystem section lists "Notifications" and
"Collaboration tools" as example Core Plugins — worth reconciling
explicitly rather than leaving it looking like a conflict with §4.4 and
§4.2 treating those as required-core. The resolution: the *baseline*
in-app ticket notification (§4.4) and presence/soft-lock layer (§4.1) are
required-core, because they're load-bearing for required-core Support
Tickets and the real-time principle itself (§1, principle 3) — same
relationship password auth has to SSO in §7.7. What `VISION.md` means by
"Notifications" and "Collaboration tools" as *optional* Core Plugins is
the layer on top of that baseline: additional delivery channels
(email/push/Slack, once the automation engine's `notify` action ships)
and full CRDT co-editing (§4.2, deferred per `ROADMAP.md`) — not the
baseline itself going away.

A module declares its **dependencies** in the manifest (e.g. Automations
depends on the event bus already existing in the kernel) so the loader can
refuse to enable a module whose dependency isn't active, rather than
letting a competition end up half-configured.

Team vs. individual participation is deliberately not in either list
above — it isn't a module to enable or disable, it's a per-competition
configuration choice (`participation_mode: 'team' | 'individual'`) on the
Competition entity itself (§6), since a single deployment may run some
competitions as team-based and others solo, possibly at the same time.
Scoring and the scoreboard read this setting to decide whether they're
ranking teams or individual accounts; nothing about the kernel or the
required-core set above changes based on which mode a given competition
uses. (This is the same toggle already scoped in `ROADMAP.md` #7.)

---

## 12. AI Integration

Two distinct assistants, with different trust boundaries:

- **Administrator assistant**: read access to competition data (stats,
  tickets, feedback, challenge health) to answer operational questions.
  This can be reasonably permissive since it's talking to an organiser.
- **Competitor assistant**: platform help and rules clarification only. It
  must not have access to flags, solution paths, or other teams' data, and
  challenge-specific help should be an explicit per-competition toggle set
  by organisers, not a default-on capability. Treat "does this leak a
  challenge solve path" as the standing constraint on every prompt this
  assistant is allowed to see, not a one-time review.

Both should be built as consumers of the same event/data layer as the rest
of the app (via the domain hooks / internal APIs), not as a separate
data-access path that has to be kept in sync by hand.

---

## 13. Core Domain Model & Submission Handling

### 13.1 Core Entities

No section so far lays out how the entities referenced throughout this
document actually relate. At a high level:

```
Competition (§6)
 ├─ RoleAssignment (§7.5) ── Role (§7.2)
 ├─ Team                     (only if participation_mode = 'team', §11.3)
 │   └─ TeamMembership ── User
 ├─ Challenge
 │   ├─ Hint
 │   └─ Submission ── User | Team   (whichever participation_mode implies)
 ├─ SupportTicket ── Challenge (optional link)
 └─ Announcement
```

Every entity below `Competition` carries `competition_id` directly or
transitively (a `Submission` scopes through its `Challenge`), consistent
with the tenancy model in §6.2 — there's no entity in the system that
sits outside a competition except `User` and `Role` themselves, which are
site-wide.

### 13.2 Flag Submission & Anti-Brute-Force

This is the one mechanic that's genuinely different from a generic SaaS
form submission: a competitor is an adversarial user by design, and flag
submission is the one endpoint they have direct incentive to script.

- **Server-side comparison only.** The flag (or its hash, for static
  flags) never reaches the client in any API response, including admin
  views that show challenge metadata — a challenge-edit screen shows
  *that* a flag is set, not the flag itself, without a separate "reveal"
  action.
- **Per-user/per-team rate limiting on the submission endpoint**
  specifically, tighter than general API rate limits — a sliding window
  with escalating backoff is enough to blunt a guessing script without
  meaningfully slowing down a human typing a real answer.
- **Idempotent on repeat-correct.** Resubmitting an already-correct flag
  doesn't re-award points or re-emit `challenge.solved` — the first
  correct submission is authoritative.
- **Every attempt is logged, not just successes** — failed attempts feed
  challenge-health analytics (Tier 3 fail-rate reporting) and give staff
  something to look at if brute-forcing is suspected, even before any
  automated defense triggers.
- **Flag types** are `static` (salted-hash exact match), `regex` (pattern,
  stored as-is), and `multiple_choice` (Tier 3 Phase 9). A multiple-choice
  challenge stores its **options** in a public `choices` list (shown to the
  competitor) and the **correct option hashed** in `flag_hash` exactly like a
  static flag — so the answer never leaves the server; the competitor submits the
  option they picked and it's graded server-side the same way. Because a finite
  option set is trivially brute-forced, multiple-choice adds a
  **competition-wide guess cap** (`Competition.mc_guess_limit`, null = unlimited,
  set in competition settings — deliberately not per-challenge): once a subject
  has used its guesses on an unsolved MC challenge, further guesses are refused
  before grading (so the block can't be probed for correctness), independent of
  the general submission rate limit above. Staff can **reset** guesses
  non-destructively (a competitor locked out by a misclick shouldn't be stuck):
  a `mc_guess_resets` row records a **cutoff** so the count only tallies
  submissions made after it — targeted at one subject or challenge-wide (bulk) —
  keeping the submission history intact for analytics/audit.
- **Scoring model** (per challenge, Tier 3 Phase 9): `static` (a fixed
  `points` award) or `dynamic` (the CTFd decay model — worth `points` initially,
  falling quadratically toward `min_points` over `decay` solves). A dynamic
  challenge's value is a property of its **solve count**, and *every* solver
  converges to the current value: on each new solve the awarded value is
  recomputed and all prior solvers' `points_awarded` are re-valued to match, so
  the scoreboard read path (sum of `points_awarded`) stays unchanged and the
  card's displayed `value` is exactly what each solve is worth right now.
- **Scoreboard freeze** (`Competition.scoreboard_frozen_at`, Tier 3 Phase 9): a
  `scoreboard_freeze` holder freezes public standings at a chosen instant
  (default now; a future time schedules it). `compute_scoreboard` then computes
  the board **as of** that time for everyone — dynamic values by solve count at
  freeze, later solves/adjustments/awards/hint-costs excluded — and the WS room
  serves that same frozen snapshot so it visibly stops moving. Staff read the
  live board with `?live=true`. Emits `scoreboard.frozen` / `scoreboard.unfrozen`.
  A freeze **stops the board from moving publicly — competitors keep solving and
  their points still count**; the UI states this (confirm on freeze + a note on
  the frozen board). It's also an automation action, so a rule can freeze on
  `competition.ended` (a lifecycle trigger the scheduler now emits).

### 13.3 File Storage & Access Control

Challenge files live in MinIO, but tenancy scoping (§6.2) has to be
enforced at the storage layer too, not just in the database:

- Object keys are namespaced by competition and challenge
  (`<competition_id>/<challenge_id>/<filename>`), mirroring the
  `competition_id` scoping applied everywhere else.
- Files are served via short-lived signed URLs, not public bucket paths —
  a link a competitor pastes into a chat shouldn't keep working after the
  challenge is unpublished or the competition ends.
- Signed-URL issuance goes through the same permission check as viewing
  the challenge itself (`challenge_view`, §7.1), so file access can't
  become a side channel around RBAC.

---

## 14. Suggested Repository Layout

```
/.claude
  CLAUDE.md        persistent Claude Code project instructions — see
                    "Keeping this file honest" in that file; it points
                    back here rather than duplicating this document

/backend
  /models          SQLAlchemy models
  /schemas         Pydantic request/response schemas
  /routers         FastAPI routers, one per domain
  /utils
    event_bus.py
    automation_engine.py
  /plugins         manifest-driven modules (§11) — required-core and
                    system modules included, per §11.3; marketplace-
                    installed third-party ones join the same directory
                    once that path opens (deferred, see ROADMAP.md)
  /alembic         migrations

/frontend
  /src
    /app           Next.js App Router pages
    /components
      /ui          design-system primitives
      /<domain>    feature components, one dir per domain
    /lib
      /hooks       one file per domain, see §8
      api.ts
      types.ts
    /stores        Zustand stores (auth, active competition, prefs)

/docs
  VISION.md
  ARCHITECTURE.md   (this file)
  ROADMAP.md
  PLUGIN_SYSTEM.md
  API_DESIGN.md
  SECURITY.md
  /adr             Architecture Decision Records
```

---

## 15. Open Questions / Not Yet Decided

Keep this section honest — update as decisions are made:

- ~~Scoreboard freeze mechanics: implemented as a scheduled event, or a
  read-path filter?~~ **(resolved, Tier 3 Phase 9.)** A **read-path filter** —
  `compute_scoreboard`'s `freeze_cutoff` computes the board as of the freeze
  instant (dynamic values by solve count at that time; later
  solves/adjustments/awards excluded) — **and** an emitted event
  (`scoreboard.frozen` / `scoreboard.unfrozen`, §13), so a freeze is both a
  staff/automation action and an audit + automation trigger.
- Plugin sandboxing: current plugin model assumes trusted, reviewed code
  running in-process. Marketplace-distributed third-party plugins (per
  `VISION.md`'s Plugin Marketplace) will need a stronger isolation story
  before that ships.
- Rate limiting / abuse prevention on the automation engine's webhook
  action, beyond the SSRF/header/value hardening in §5.4 (that part landed
  in Tier 3 Phase 2, ADR-0013; also still open there: the resolve-then-connect
  TOCTOU / connection pinning). Rate limiting needs to be sensible
  rather than a flat cap: a single rule can legitimately fire thousands of
  times in quick succession on a large event (e.g. a "challenge solved"
  notification rule during a 1,000+ competitor competition isn't abuse,
  it's the expected load), so a naive per-rule or per-minute ceiling would
  throttle real competitions, not just runaway triggers. Likely needs some
  combination of: rate limiting scoped to the *destination* (protect the
  external endpoint, e.g. a Slack webhook, from being hammered) rather
  than the rule itself; batching/coalescing near-simultaneous triggers of
  the same rule into a single outbound call where the action type
  supports it (e.g. "5 challenges solved in the last 10s" instead of 5
  separate calls); and a genuine runaway-loop guard (e.g. a rule whose own
  actions re-trigger its own conditions) that's about detecting
  automation feedback loops specifically, not competition scale. Worth
  revisiting with real trigger-volume numbers from a large event before
  picking specific thresholds.
- ~~Notification mute: whether a user can mute the ticket audio cue from
  §4.4 entirely, or whether it's always on given there's only one category to
  mute.~~ **(resolved, Tier 3 Phase 9.)** Per-user notification preferences
  (§4.4, `GET/PUT /api/notifications/preferences`) expose in-app category mutes
  (tickets / automations, honored centrally in `create_notifications`) plus
  client-honored `browser` / `sound` delivery hints — so a judge can go
  visual-only.
- ~~Scoreboard tie-breaking: two teams/individuals at equal points — ranked by
  earliest time reaching that score, or some other rule?~~ **(resolved.)**
  Standard CTF convention: points descending, ties broken by the **earliest time
  the subject reached its current score** — `compute_scoreboard`'s `sort_key`
  uses each subject's last-awarding solve time as the secondary key (subjects
  with no solves sort last).
- ~~Administrator bootstrap hardening (see ADR-0010, which superseded
  ADR-0007).~~ **(resolved, ADR-0017, which superseded ADR-0010.)** There is
  **no seeded default admin** in production: a fresh install ships with no
  administrator and is *unconfigured* until an operator completes the
  **first-run setup wizard** (`/setup`), which creates the owner account with
  operator-chosen credentials — no known-default admin ever exists
  (`instance_needs_setup` gates the wizard and blocks public registration until
  an owner exists). The test suite still seeds `admin@example.com` / `changeme`
  in its fixtures only.
- ~~Event-dispatch model & delivery durability~~ **(resolved, ADR-0012).**
  `emit()` now runs foreground handlers awaited (the default — the audit log
  stays synchronous and lossless, tests stay deterministic) and schedules
  `background=True` handlers fire-and-forget, so a slow/external handler (the
  automation `webhook`/`send_email` actions, §5.3) never blocks the request and
  §3.1's "non-blocking emit" is real for the handlers that need it. A durable
  **outbox** for at-least-once delivery across a crash/restart was deliberately
  *not* built — it remains an additive layer behind the same `background` lane
  if that requirement ever lands. ADR-0005's single-process scope is unchanged.
