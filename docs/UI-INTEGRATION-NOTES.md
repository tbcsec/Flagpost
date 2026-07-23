# UI Integration Notes — Flagpost design handoff

This records what happened when the **Flagpost UI handoff** (a full-product
HTML/CSS mock from Claude Design, spanning every tier) was integrated into the
real Next.js frontend.

The mock is a single-page prototype of the *whole* product vision — dashboard,
challenges, scoreboard, participants, support, analytics, automations, a full
admin console, notifications, per-competition theming, drag-and-drop dashboard
widgets. The shell and every section were built, but only the sections with a
real backend are wired; the rest render as faithful UI seeded with placeholder
data and flagged in-app with a **"Preview — …"** banner (`NotWiredNote`).

**Status: Tier 2 complete; Tier 3 in progress (Phases 0–8 shipped).** Since the
original handoff the backend has caught up through all of Tier 1 and Tier 2 and
into Tier 3 (per `claude_plans/phase_3.md`): the notification bell (Phase 0), the
whole automation surface — rules + the visual builder (Phases 1–3), feedback /
surveys (Phase 4), challenge & team analytics (Phase 5), **dashboard
customization** — drag-reorder / resize / show-hide edit mode (Phase 6),
**collaborative CRDT notes** — a team challenge scratchpad + staff ticket notes
(Phase 7), and **guided first-run empty states** — a reusable `EmptyState` across
challenges/scoreboard/support/feedback + a manager dashboard getting-started
guide (Phase 8) — are all real too. The tables below are kept current; the remaining placeholder surfaces
are the Admin → Users directory, the Admin → Plugins toggle UI (its
per-competition module-toggle *backend* now exists), Admin → Dashboard global
stats, and per-user notification *preferences* (the inbox itself is wired).

## Design system adopted

- `frontend/src/app/globals.css` — the token layer now matches the handoff DS.
  The Tier 0 scaffold's **placeholder blue** `--primary` was replaced with
  Flagpost **signal green** (`155 61% 44%` dark / `156 67% 37%` light), and
  `--success` / `--ring` reference the same brand green by intention
  (LOGO-SPEC §2.3). Added `--warning`, brand source tokens (`--fp-*`), the
  `--font-display` (Space Grotesk) family, and `--radius-full`.
- New primitives: `components/ui/badge.tsx`, `components/brand/flagpost-mark.tsx`
  (`FlagpostMark` + `Lockup`, adapted from `docs/branding/FlagpostMark.jsx`).
- App shell: `components/app/app-shell.tsx` (persistent sidebar + topbar with the
  competition switcher, notifications, and the light/dark toggle) and
  `components/app/section-header.tsx` (`SectionHeader`, `NotWiredNote`).
- Theming is site-wide (Tier 2 Phase 4, §9): an admin sets the default palette +
  accent (Admin → Appearance), stored in a SiteSettings singleton and read
  publicly. `ThemeApplier` (mounted above every page) applies palette + accent to
  `<html>`; a user can override just the *palette* for themselves via the topbar
  palette menu (`paletteOverride` on the auth store). Shipped palettes: Harbor,
  Eclipse, Umbra (dark), Daybreak, Sandstone (light).

## Routing

Authenticated surface moved under a `(app)` route group with the shell as its
layout and an auth guard. `/login` and `/register` stay outside the shell (now
carrying the brand lockup). The old `/` competition-list page and
`/competitions/[id]` detail page were removed — their functions moved into the
shell (Admin → Competitions, and the per-section pages scoped by the topbar
switcher). `components/competitions/competition-list.tsx` was deleted as dead
code.

## Wired to the real backend

| Section | Status |
| --- | --- |
| Sign in / Register / brand lockup | **Wired** (existing auth hooks) |
| Topbar competition switcher | **Wired** (`useCompetitions`, active id in the auth store) |
| Challenges — browse grid + category chips | **Wired** (`useChallenges`, `useCategories`) |
| Challenges — detail dialog (title/points/category/description) | **Wired** (description rendered read-only via `richTextToPlain`) |
| Challenges — flag submission + solve state | **Wired** (Phase 6 — `useSubmitFlag`, solved/solve_count badges, first-blood) |
| Challenges — "Manage challenges" authoring (CRUD, categories, publish, attachments) | **Wired** (reuses `ChallengeAdmin`) |
| Scoreboard — live rankings | **Wired** (Phase 7 — `useScoreboard`: REST initial load + WebSocket room updates, first-frame auth, backoff reconnect) |
| Announcements — post + live banner + dashboard widget | **Wired** (Phase 8 — `useAnnouncements`: REST + WS room, `NewAnnouncementDialog`) |
| Hints — reveal (competitor) + authoring (editor) | **Wired** (Phase 9 — `useHints`: reveal-on-request with cost, hidden body until revealed; scoreboard deducts cost live) |
| Participants — team mode (create/join/leave, browse teams) | **Wired** (reuses `TeamPanel`) |
| Participants — individual mode (competitor roster + standing) | **Wired** (Tier 3 Phase 9) — `GET /participants` lists Participant-role holders with join time / solves / rank / points (reusing the scoreboard computation); `ParticipantsPanel` shows a "your standing" summary + the roster (`use-participants`) |
| Competition Settings | **Wired** (`CompetitionSettingsForm` on the active competition) |
| Admin → Competitions (list + New competition) | **Wired** (`useCompetitions`, `CreateCompetitionDialog`) |
| Profile — change password | **Wired** (new `authApi.changePassword` + `useChangePassword`) |
| Lobby — join public / join by code | **Wired** (pre-Tier-2 — `useJoinCompetition` / `useJoinByCode`; refetches permissions so the nav leaves the lobby) |
| Role-aware navigation | **Wired** (pre-Tier-2 — `useAccess` off `/me/permissions` gates manager-only nav + the Admin section; direct admin URLs are guarded) |
| Admin → Event log | **Wired** — audit-log viewer over every emitted event (§3.3), gated on `view_audit_log`; GitLab-style filtering by event/competition/team/actor/time/free-text, pagination, expandable payloads (`use-audit-log`) |
| Dashboard | **Wired** (Tier 2 Phase 1 + Tier 3 Phase 6) — widget-registration architecture (§10.1) off `dashboard` module endpoints: manager stats/recent-solves/challenge-health/support-queue, participant standing/solves, announcements. Managers (`customize_dashboard`) get an **edit mode** (§10.2–10.5): drag-reorder, per-widget size-cycle, show/hide, save / cancel / reset-to-default, persisted per-user in `dashboard_layouts` (`use-dashboard`, `DashboardGrid`) |
| Support tickets | **Wired** (Tier 2 Phase 2) — `tickets` module: competitor create/reply, staff assign/resolve/internal-notes, ownership scoping; live thread + staff-queue WS rooms with the §4.4 audio cue (`use-tickets`) |
| Presence indicators | **Wired** (Tier 2 Phase 3, §4.1) — WS presence with debounced clear: "N others viewing" on the challenge dialog (new presence-only `challenge` room) and "a judge is looking at this ticket" on the ticket thread (`usePresence` + `PresenceIndicator`) |
| Admin → Appearance (site-wide theming) | **Wired** (Tier 2 Phase 4, §9) — platform name + palette + accent (preset or custom hex) with live preview, `manage_site_settings`-gated `site_settings` module; login/register/sidebar/tab-title brand from the public read (`use-site-settings`, `lib/theme.ts`) |
| Admin → Roles (custom role editor) | **Wired** (Tier 2 Phase 5, §7.4) — `roles` module gated on `manage_roles`: list + permission catalog, create/clone/edit/delete custom roles, assign(by-email)/unassign; system roles read-only, last-admin guard (`use-roles`) |
| Notifications (topbar bell) | **Wired** (Tier 3 Phase 0, §4.4) — real per-user inbox: `notifications` required-core module, `/ws/user/<id>` live push, list/mark-read/read-all; ticket events routed like the audio cue (`use-notifications`). Per-user *preferences*/mute still unbuilt |
| Automations (competition + admin) | **Wired** (Tier 3 Phases 1–3, §5) — the `automations` optional module + engine (nine §5.3 actions incl. `open_survey`, per-competition toggle, plus the time-based `competition.time_remaining` trigger via a scheduler) and the §5.5 **visual rule builder**: catalog-driven When→If→Then editor for competition + global rules, plus a personal notify-self section (`use-automations`, `rule-builder`) |
| Feedback / surveys | **Wired** (Tier 3 Phase 4, #22) — the `feedback` optional module: staff survey builder (5 question types, reorder, open/close), competitor response form, results dialog (histograms/tallies/text) + CSV export; a submission emits `feedback.submitted`, a live automation trigger (`use-feedback`) |
| Analytics | **Wired** (Tier 3 Phase 5, #23) — the `analytics` optional module (staff, `view_competition_analytics`): overview + per-challenge table (solves / attempts+fails / completion rate / avg solve time / hints / linked tickets) and a competitors/teams ranking (rank / points / solves / first bloods / tickets / last solve), read off existing submission data (`use-analytics`) |
| Collaborative notes | **Wired** (Tier 3 Phase 7, §4.2, ADR-0014) — the required-core `collab` module: a **team per-challenge scratchpad** in the challenge dialog and **staff notes** on a ticket thread, both live-collaborative rich text (Y.js under TipTap over a `note/<doc_key>` WS room, dumb-relay transport + blob persistence). Scoped per-request — team membership / `ticket_view_internal_notes` (`CollabNote`, `lib/collab`) |

## Built as UI, NOT wired (placeholder data + in-app "Preview" banner)

These need features that are still on the roadmap. UI is in place so they're not
a retrofit later; **none of the data is real**.

- **Dashboard** — now fully wired *and customizable* (Tier 2 Phase 1 + Tier 3
  Phase 6, see the wired table above). The widget-registration architecture that
  shipped as a fixed layout made the drag-and-drop customization layer additive,
  exactly as intended (§10.2) — it's now built for the manager dashboard.
- **Admin → Dashboard** (global stats / module health) — no aggregate endpoint.
- **Admin → Users** — no user-directory / create / ban API. (Note: role
  *assignment* is handled on Admin → Roles by email, so no directory is needed
  for that.)
- **Admin → Site settings** (SMTP / AI / integrations) — deferred; the theming
  half of this page is now real on Admin → Appearance (see the wired table).
  (Note: the automation `send_email` action does use SMTP config, but there's no
  admin UI to set it — it's env-configured, §5.3.)
- **Admin → Plugins** — the per-competition module enable/disable **backend** is
  now real (`GET`/`PUT /api/competitions/{id}/modules`, Tier 3 Phase 1), but this
  page still renders the static `PLUGINS` list; a UI over the real toggle is
  unbuilt.
- **Profile → notification preferences** — the notification *inbox* is wired
  (topbar bell, see above), but per-user mute/channel preferences aren't built.
- **Lobby join actions / Admin archive+delete competition** — no endpoint;
  buttons present but disabled.

## Deliberately not carried over from the mock

- The mock's **"Preview as (demo)" role switcher** — real RBAC now drives the
  nav instead. `GET /api/auth/me/permissions` surfaces the caller's effective
  permissions and `useAccess` gates the sidebar (manager-only items, the Admin
  section) and the lobby state; the demo switcher isn't needed.
- **Per-competition theming** override examples (Tier 2) — the token layer
  supports it, but no competition-scoped theming UI was built.

## Pre-Tier-2 enhancements (in addition to the wired features above)

- **Toasts** (`stores/toast` + `Toaster`) on team join/leave, announcement post,
  hint reveal, settings save, password change, competition join, and solves.
- **Loading skeletons** (`ui/skeleton`) and empty states on the challenge and
  scoreboard screens.
- **Scoreboard polish** — medal ranks for the top three and a colour flash on a
  row whose points change from a live update.
- **Solve celebration** — the brand mark + points on a correct flag, plus a
  first-blood toast.
- **Persisted theme** — the per-user palette override is saved to `localStorage`
  (a no-flash inline script re-applies it before first paint); the site-wide
  default + accent are set by an admin on Admin → Appearance (Tier 2 Phase 4).
- **Responsive shell** — the sidebar becomes an off-canvas drawer under `md`
  (hamburger in the topbar).
- **Timestamps** read as UTC via `lib/datetime` (the backend also now serializes
  aware UTC through the `UtcDateTime` column type).

## Placeholder data

All lives in `frontend/src/lib/placeholder-data.ts`, clearly labelled. Every
consumer is one of the "not wired" surfaces above. Deleting that file should
only affect placeholder screens.
