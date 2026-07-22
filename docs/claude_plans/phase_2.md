# Tier 2 — "Makes It Good, Not Just Functional": Phased Plan

## Context

Tier 1 (Minimum Viable Competition) is complete: a competition can be run end
to end — teams, challenges, files, submission + scoring, a live WebSocket
scoreboard, announcements, and hints. Tier 2 (`docs/ROADMAP.md` items 16–21)
turns "we could technically use this" into "we'd rather use this than what we
have": an operational dashboard, support tickets, presence, **site-wide
theming**, and a custom-role editor.

**Scope changes from the original ROADMAP framing (owner decisions):**
- **Challenge lifecycle (#17) is deferred to a future tier** — it wants more
  design first, and will be re-added and planned properly then. Not built in
  this tier.
- **Per-competition theming (#20) is dropped in favour of site-wide theming.**
  Themes are globally scoped for now; the per-competition/white-label variant
  may return later if demand warrants it. This tier delivers only the site-wide
  version (Phase 4 below).

Governing docs: `ARCHITECTURE.md` §10 (dashboard widget model), §4.1 (presence /
real-time), §4.4 (in-app notifications + the ticket audio cue), §7.4 (custom
roles), §9 (theming / token layer), §13 (domain model). ADR-0009 (synchronous
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

## Phase 0 — Close Tier 1 gaps — ✅ DONE (landed pre-Tier-2)

Gap-remediation from the end-of-Tier-1 review, delivered ahead of Tier 2 proper.
All items shipped:

- **Competition registration / join** — `POST /api/competitions/{id}/join`
  (public self-serve) and `POST /api/competitions/join` (by invite code) grant
  the Participant role idempotently, emitting `competition.member_joined`; the
  Lobby join actions are wired. This makes individual-mode competitions playable.
- **Visibility enforced on reads** — private competitions are hidden from the
  list and 404 to non-members; a global admin sees all.
- **Role-aware navigation** — `GET /api/auth/me/permissions` + `useAccess` gate
  the sidebar/sections; direct admin URLs are guarded.
- **Timestamps** serialize as aware UTC via the `UtcDateTime` column type.

## Phase 1 — Judge/admin dashboard (#16, §10) — ✅ DONE

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
  view permissions. (The support-queue widget is registered later, in Phase 2.)
- Frontend: replace the placeholder dashboard (`(app)/page.tsx`) with the real
  widget grid; a `use-dashboard.ts` hook module. Fixed layout; no drag-drop UI.
- Tests: widget registry (sizes/defaults), each stats endpoint's scoping + RBAC.

## Phase 2 — Support tickets (#18, §4.4) — ✅ DONE

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

## Phase 3 — Presence indicators (#19, §4.1) — ✅ DONE

Cheap now that the WS infrastructure exists — it's the "feels alive" detail.

- The real-time layer gained **presence**: a room type opts in by registering a
  `presence_member` builder (`(db, user, room_id, mode) → {id, name, role, mode}`),
  and the connection manager tracks the per-user set (deduped across tabs) and
  broadcasts a `{"type": "presence", "members": [...]}` frame on every change.
  **Debounced clearing** (`ws_presence_grace_seconds`, default 5s) absorbs brief
  reconnects so the "who's here" list doesn't flicker. Presence stays WS-level
  state — no event-bus event, no REST, no migration. The optional `view`/`edit`
  `mode` rides the same first frame as the auth token.
- Surfaces: a `challenge/<id>` presence-only room drives "N others viewing" on the
  challenge detail dialog; the Phase 2 `ticket/<id>` room now also carries
  presence, so a competitor sees "a judge is looking at this ticket" and staff
  see who else is on the thread.
- Frontend: `usePresence` hook (+ pure `summarizePresence`) and a reusable
  `PresenceIndicator` (stacked avatar chips).
- Tests: manager-level join/leave, dedup, debounced clear, reconnect-cancels
  (`tests/test_presence.py`); end-to-end join/broadcast/clear + payload shape +
  staff-role + RBAC (`tests/test_realtime.py`); `summarizePresence` (vitest).

## Phase 4 — Site-wide theming (§9) — ✅ DONE

Themes are **global / site-wide only** (per-competition dropped, see Context).
Owner decision during the phase: palette/background stays a **curated-preset**
choice (not a free-form background picker) — a palette is ~15 interdependent
channels that must hold contrast + elevation + hue together, so presets are the
only way to guarantee legibility; the accent gets the full custom-hex treatment
because it's one colour into a swap-designed slot. The shipped presets are
bespoke (not the reference mockup's): **Harbor/Eclipse/Umbra** (dark),
**Daybreak/Sandstone** (light).

- Backend (`site_settings` required-core module): a **SiteSettings singleton**
  (lazy `get_or_create`, no data migration needed) holding platform name +
  default palette + accent. Public `GET /api/site-settings` (login/register
  brand before auth) and `PUT` gated on the new global **`manage_site_settings`**
  (§7.1); the update emits **`site.settings_updated`** (§3.2). Palette/accent are
  regex-validated (a slug, or `#RRGGBB`) so neither can inject CSS/attributes.
  Migration adds the table. **System roles now re-sync from the catalog on every
  startup** (`seed_system_roles`) so the new permission actually reaches an
  already-migrated Administrator — the general fix for "a permission added after
  install".
- Frontend: unique palettes in `globals.css`; a `lib/theme.ts` registry + colour
  math (hex→HSL, YIQ-based on-accent foreground, `resolveTheme`/`applyTheme`); a
  `ThemeApplier` mounted above every page that applies palette (per-user override
  ?? site default) + accent, with a **no-flash inline script** priming from a
  cached resolved theme. Admin → Appearance wired with live preview; a topbar
  **palette menu** for the per-user override; the accent overrides only
  `--primary`/`--ring` (+ foreground) — `--success` and the **logo never take the
  accent** (LOGO-SPEC §7). Login/register/sidebar/tab-title pick up the platform
  name via the public read.
- Tests: settings round-trip, RBAC, validation, the event (backend); the colour
  math + `applyTheme` (vitest).

## Phase 5 — Custom role editor, admin (#21, §7.4) — ✅ DONE

The three built-in roles already cover Tiers 0–1; this lets an organiser hand
out narrower access (e.g. a challenge-author-only role). **This completes Tier 2.**

- Backend (`roles` required-core module): roles API gated on `manage_roles` —
  list roles, the categorized permission **catalog** endpoint, create/clone
  (from any role, or blank), edit + delete **custom** roles, and
  list/assign/unassign assignments. Custom roles default to `scope: competition`
  (§7.4); permission keys are catalog-validated. Invariants: **system roles are
  read-only** (409 on edit/delete), **assignment scope must match the role**, a
  role **can't be deleted while assigned**, and the **last Administrator can't be
  unassigned** (no lockout). Assignment is **by email** (no user directory
  needed). Emits `role.created`/`updated`/`deleted`/`assigned`/`unassigned`
  (added to §3.2). No migration — the role/assignment tables are Tier-0.
- Frontend: wired Admin → Roles — role cards (system + custom), clone, a New-role
  dialog, the categorized permission **matrix** (editable for custom, read-only
  for system; global permissions hidden on competition-scoped roles via
  `groupCatalog`), delete, and the assignment form + list; a `use-roles.ts` hook.
- Tests: clone/edit/delete, catalog, scope defaults, RBAC, system-role
  immutability, the last-admin guard, the events, and a custom role gating a
  request end to end (backend); `groupCatalog` (vitest).

---

## Cross-cutting notes

- **Events:** new to §3.2 this tier (add there first): `site.settings_updated`
  (Phase 4), `role.created`/`role.updated`/`role.deleted` (Phase 5). The
  ticket.* events (Phase 2) already exist. (`competition.member_joined` from the
  now-complete Phase 0 already landed.)
- **Dashboard architecture is the load-bearing decision** (§10.1): build widgets
  as self-contained, registered, size-declaring units in Phase 1 even with a
  fixed layout, so the Tier-3+ drag-drop layer is additive.
- **RBAC:** `ticket_*`, `manage_roles`, `customize_dashboard` already exist in
  §7.1. One catalog addition expected: **`manage_site_settings`** (global,
  Phase 4). No per-competition theming permission is needed (theming is global).
- **New infra first-use:** WS presence (Phase 3) and the ticket audio cue
  (Phase 2) are the only genuinely new real-time mechanics; both extend the
  Tier 1 Phase 7 WebSocket layer rather than adding infrastructure.

## Verification (per phase + at the end)

1. `cd backend && .venv/bin/pytest` and `cd frontend && npm run test` green.
2. Migrations apply cleanly up **and** down; native dev servers still start.
3. End-to-end smoke on the running stack: as staff, watch the dashboard update
   as solves land; a competitor opens a ticket tied to a challenge and staff
   resolves it (with the audio cue and live thread); two clients see each
   other's presence on a challenge; set a site-wide accent in Admin →
   Appearance and see the whole app (and the login screen) recolour; clone Judge
   into a custom role, assign it, and confirm it gates access.

## Out of scope (deferred / future tiers)

- **Challenge lifecycle (#17)** — Draft → Review → Published + author field.
  Deferred to a future tier for fuller design (owner decision).
- **Per-competition / white-label theming** — dropped for now in favour of
  site-wide theming (Phase 4); may return later if demand warrants (owner
  decision).
- Dashboard drag-and-drop customization (§10.2), the *full* challenge lifecycle
  (testing sign-off, version history), ticket routing rules + response-time
  analytics, email/push notification delivery, CRDT co-editing (§4.2), the
  automation engine, AI assistants, and the plugin marketplace / extension-slot
  UI. Feedback/surveys, challenge analytics, onboarding/empty-state and the
  accessibility/responsive pass are Tier 3.
