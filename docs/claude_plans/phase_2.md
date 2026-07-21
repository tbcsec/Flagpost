# Tier 2 — "Makes It Good, Not Just Functional": Phased Plan

## Context

Tier 1 (Minimum Viable Competition) is complete: a competition can be run end
to end — teams, challenges, files, submission + scoring, a live WebSocket
scoreboard, announcements, and hints. Tier 2 (`docs/ROADMAP.md` items 16–21)
turns "we could technically use this" into "we'd rather use this than what we
have": an operational dashboard, a lightweight challenge lifecycle, support
tickets, presence, per-competition theming, and a custom-role editor.

Governing docs: `ARCHITECTURE.md` §10 (dashboard widget model), §4.1 (presence /
real-time), §4.4 (in-app notifications + the ticket audio cue), §7.4 (custom
roles), §9 (per-competition theming), §13 (domain model). ADR-0009 (synchronous
event dispatch) is due for revisiting **only** if a genuinely slow handler
appears — Tier 2 handlers stay in-process and fast, so it holds.

Conventions held throughout (unchanged from Tier 1): every mutation emits a
past-tense `<entity>.<verb>` event already in §3.2 (add new ones there first);
every tenant-scoped table uses `CompetitionScopedMixin` and every query filters
by `competition_id`; permission checks go through `require_permission`; one
router + one hook module per domain; colours/spacing from tokens; new backend
features register through the module loader (§11.1). One migration and a green
pytest + vitest run per phase; one commit per phase.

---

## Phase 0 — Close Tier 1 gaps (recommended before Tier 2 proper)

Gap-remediation surfaced by the end-of-Tier-1 review. Not new Tier 2 features,
but Tier 2 (tickets, dashboard, the role editor) assumes a working participant-
access model and honest nav, so these come first. **Flag for review — decide
which of these to take.**

- **Competition registration / join (the material gap).** Today the only path
  to the competition-scoped Participant role (and therefore `challenge_view`)
  is creating or joining a *team*. Individual-mode competitions have no teams,
  so a solo competitor cannot gain access at all without an admin hand-inserting
  a `RoleAssignment` — i.e. solo competitions aren't actually playable through
  the UI. Add `POST /api/competitions/{id}/join` (self-serve for `public`;
  invite-code/None for `private`) that grants the Participant role idempotently,
  emitting **`competition.member_joined`** (new — add to §3.2 first). Wire the
  Lobby's "Join" actions (currently inert) and keep team-join granting the role
  too. Migration only if an invite-code column is added to `Competition`.
- **Enforce competition visibility on reads.** `GET /api/competitions` and
  `GET /{id}` currently return every competition (private included) to any
  authenticated user, so `visibility=private` is cosmetic. Scope the list to
  public competitions + those the caller is a member/organiser of; 404 a private
  competition to a non-member. No migration.
- **Role-aware navigation (frontend honesty).** `/me` doesn't surface the
  caller's permissions, so the shell shows every nav item (Admin included) to
  everyone — the backend 403s protect data, but the UI misleads. Add
  `GET /api/auth/me/permissions` (effective permission keys, per active
  competition + global) and gate the sidebar/sections on it, replacing the
  "everyone sees everything" stopgap. This also unblocks the dashboard's role
  split (Phase 1) and the ticket competitor-vs-staff views (Phase 3).
- *(Optional cleanup)* Serialize timestamps as tz-aware UTC so clients don't
  have to compensate (the frontend currently normalizes naive-UTC in
  `lib/datetime.ts`).

## Phase 1 — Judge/admin dashboard (#16, §10)

Build the **widget-registration architecture** now (§10.1) — even shipping a
fixed layout — so drag-and-drop (§10.2, deferred) is additive, not a rewrite.

- Widget registry: each dashboard section is a self-contained widget (id,
  component ref, declared legitimate sizes, default position/size) that fetches
  its own data via domain hooks (§8) and renders at every size it declares. The
  page renders a fixed-column grid + the widgets in a saved (for now: default)
  order — it never hardcodes `<StatsPanel/>` above `<Queue/>`.
- Backend: aggregate/read endpoints the widgets need — active competitors,
  recent solves, challenge health (solve counts / attempt volume off the
  submissions data), scoreboard summary. Read-only; gated on competition-scoped
  view permissions. (The support-queue widget is registered later, in Phase 3.)
- Frontend: replace the placeholder dashboard (`(app)/page.tsx`) with the real
  widget grid; a `use-dashboard.ts` hook module. Fixed layout; no drag-drop UI.
- Tests: widget registry (sizes/defaults), each stats endpoint's scoping + RBAC.

## Phase 2 — Challenge lifecycle, lightweight (#17)

Smallest domain change; sits entirely in the challenges module.

- Extend `Challenge`: insert **`review`** between `draft` and `published`
  (`draft → review → published`) and add an **`author_id`** (SET NULL). No
  testing sign-off, no version history (that's the full §-VISION lifecycle,
  deferred). Transition endpoints gated on `challenge_edit`/`challenge_publish`;
  publishing still requires a flag. Reuse `challenge.updated`/`challenge.published`
  (no new events). Migration adds the column + widens the state check.
- Frontend: state badges (draft/review/published) and transition controls in the
  challenge editor; the browse list already hides non-published from competitors.
- Tests: legal/illegal transitions, author capture, publish-still-needs-a-flag.

## Phase 3 — Support tickets (#18, §4.4)

Required-core module (§11.3), first consumer of the WS layer beyond scoreboard/
announcements.

- Models: `Ticket` (competition-scoped, optional `challenge_id` link, status
  `open`/`resolved`, opener) + `TicketMessage` (thread; author, body, optional
  internal-note flag for staff). Endpoints: competitor create + reply
  (`ticket_view`, `ticket_respond`), staff respond/assign/resolve
  (`ticket_assign`, + `ticket_view_internal_notes` for internal notes). Events
  `ticket.created`, `ticket.assigned`, `ticket.resolved` (all already in §3.2).
- Real-time: per-ticket WS room for the live thread (§4.1), plus the §4.4 **audio
  cue scoped exclusively to tickets** — a new ticket cues staff; a reply cues
  whichever side didn't post. This is the baseline in-app notification (bell +
  the one sanctioned sound), independent of the deferred automation `notify`.
- Frontend: wire the placeholder Support page — ticket list + filters (staff),
  "New ticket" (competitor, optionally tied to a challenge), and the live thread
  view; a `use-tickets.ts` hook. Register a **support-queue dashboard widget**
  (Phase 1's registry) here.
- Tests: create/reply/resolve RBAC, internal-note visibility, scoping, the
  ticket events, and the WS thread broadcast.

## Phase 4 — Presence indicators (#19, §4.1)

Cheap now that the WS infrastructure exists — it's the "feels alive" detail.

- Extend the real-time layer with **presence**: on joining a resource room a
  client is tracked with the minimal §4.1 payload (id, display name, role,
  optional `view`/`edit` mode); the room broadcasts the presence set. **Debounced
  clearing** (a short grace period) so a brief reconnect doesn't flicker the
  "who's here" list. Presence is WS-level state, not an event-bus event.
- Surfaces: "N people viewing this challenge" on the challenge detail; "a judge
  is looking at this ticket" / soft-lock banner on the ticket thread (reuses the
  Phase 3 room).
- Frontend: a small presence hook + indicator components. No new REST/migration.
- Tests: presence join/leave, debounced clear, payload shape.

## Phase 5 — Per-competition theming (#20, §9)

White-labelling without a fork — the token layer already supports it (every
colour is an HSL-channel variable).

- Backend: a `theme` on `Competition` (accent + optional palette overrides,
  stored as the small documented override set). `edit_competition`-gated;
  emits `competition.updated`. Migration adds the column (JSON).
- Frontend: apply the overrides on a competition-scoped scope element
  (`data-competition-theme` with `--primary` etc.) so the whole surface
  recolours; an accent picker in the competition settings / Admin → Appearance
  (wire the placeholder). The **logo never takes the theme** (LOGO-SPEC §7 — use
  the mono mark on a branded ground).
- Tests: override round-trips; scoping (one competition's theme never leaks).

## Phase 6 — Custom role editor, admin (#21, §7.4)

The three built-in roles already cover Tiers 0–1; this lets an organiser hand
out narrower access (e.g. a challenge-author-only role).

- Backend: roles API — list roles (system + custom), read a role's permission
  set, create/clone (from a system or custom role or blank) and edit permissions
  from the §7.1 catalog, delete custom roles; assign/unassign to users per
  competition or global. Gated on `manage_roles`. Custom roles default to
  `scope: competition` (§7.4). Expose the permission catalog (categorized) via
  an endpoint for the editor. New events likely needed — **add `role.created` /
  `role.updated` / `role.deleted` to §3.2 first** (none exist yet). Migration:
  none if the role/assignment tables already suffice (they do — Tier 0).
- Frontend: wire the placeholder Admin → Roles page — role cards, clone, the
  categorized permission matrix (real toggles), and assignment; a `use-roles.ts`
  hook. System roles are read-only (clone-to-edit).
- Tests: clone/edit/delete, catalog exposure, scope defaults, RBAC, and that a
  custom role's permissions actually gate a request end to end.

---

## Cross-cutting notes

- **Events:** new to §3.2 this tier (add there first): `competition.member_joined`
  (Phase 0), `role.created`/`role.updated`/`role.deleted` (Phase 6). Everything
  else (ticket.*, challenge.*) already exists.
- **Dashboard architecture is the load-bearing decision** (§10.1): build widgets
  as self-contained, registered, size-declaring units in Phase 1 even with a
  fixed layout, so the Tier-3+ drag-drop layer is additive.
- **RBAC:** `ticket_*`, `manage_roles`, `customize_dashboard` etc. already exist
  in §7.1 — no catalog additions expected except possibly a `theme`/appearance
  permission (reuse `edit_competition` unless a narrower one is wanted).
- **New infra first-use:** WS presence (Phase 4) and the ticket audio cue
  (Phase 3) are the only genuinely new real-time mechanics; both extend the
  Phase 7 layer rather than adding infrastructure.

## Verification (per phase + at the end)

1. `cd backend && .venv/bin/pytest` and `cd frontend && npm run test` green.
2. Migrations apply cleanly up **and** down; native dev servers still start.
3. End-to-end smoke on the running stack: as staff, watch the dashboard update
   as solves land; move a challenge draft → review → published; a competitor
   opens a ticket tied to a challenge and staff resolves it (with the audio cue
   and live thread); two clients see each other's presence on a challenge;
   apply a competition accent and see it recolour; clone Judge into a custom
   role, assign it, and confirm it gates access.

## Out of scope (Tier 3+ / deferred, per ROADMAP)

Dashboard drag-and-drop customization (§10.2), full challenge lifecycle
(testing sign-off, version history), ticket routing rules + response-time
analytics, email/push notification delivery, CRDT co-editing (§4.2), the
automation engine, AI assistants, and the plugin marketplace / extension-slot
UI. Feedback/surveys, challenge analytics, onboarding/empty-state and the
accessibility/responsive pass are Tier 3.
