# UI Integration Notes — Flagpost design handoff

This records what happened when the **Flagpost UI handoff** (a full-product
HTML/CSS mock from Claude Design, spanning every tier) was integrated into the
real Next.js frontend.

The mock is a single-page prototype of the *whole* product vision — dashboard,
challenges, scoreboard, participants, support, analytics, automations, a full
admin console, notifications, per-competition theming, drag-and-drop dashboard
widgets. The backend today only reaches **Tier 1 Phase 5** (auth, competitions,
teams, challenges + categories, file attachments). So the shell and every
section were built, but only the sections with a real backend are wired; the
rest render as faithful UI seeded with placeholder data and flagged in-app with
a **"Preview — …"** banner (`NotWiredNote`).

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
- Palette is a client-state preference on the auth store (`palette` /
  `togglePalette`); the topbar mirrors it onto `<html data-palette>`.

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
| Competition Settings | **Wired** (`CompetitionSettingsForm` on the active competition) |
| Admin → Competitions (list + New competition) | **Wired** (`useCompetitions`, `CreateCompetitionDialog`) |
| Profile — change password | **Wired** (new `authApi.changePassword` + `useChangePassword`) |
| Lobby — join public / join by code | **Wired** (pre-Tier-2 — `useJoinCompetition` / `useJoinByCode`; refetches permissions so the nav leaves the lobby) |
| Role-aware navigation | **Wired** (pre-Tier-2 — `useAccess` off `/me/permissions` gates manager-only nav + the Admin section; direct admin URLs are guarded) |
| Admin → Event log | **Wired** — audit-log viewer over every emitted event (§3.3), gated on `view_audit_log`; GitLab-style filtering by event/competition/team/actor/time/free-text, pagination, expandable payloads (`use-audit-log`) |
| Dashboard | **Wired** (Tier 2 Phase 1) — widget-registration architecture (§10.1) with fixed per-audience layouts off `dashboard` module endpoints: manager stats/recent-solves/challenge-health/support-queue, participant standing/solves, announcements (`use-dashboard`) |
| Support tickets | **Wired** (Tier 2 Phase 2) — `tickets` module: competitor create/reply, staff assign/resolve/internal-notes, ownership scoping; live thread + staff-queue WS rooms with the §4.4 audio cue (`use-tickets`) |

## Built as UI, NOT wired (placeholder data + in-app "Preview" banner)

These need features that are still on the roadmap. UI is in place so they're not
a retrofit later; **none of the data is real**.

- **Dashboard** — now fully wired (Tier 2 Phase 1, see the wired table above).
  Ships as a **fixed layout** built on the widget-registration architecture so
  the drag-and-drop customization layer is additive later (§10.2, deferred).
- **Analytics** — Tier 3.
- **Automations** (competition + admin) — deferred past MVP.
- **Admin → Dashboard** (global stats / module health) — no aggregate endpoint.
- **Admin → Users** — no user-directory / create / ban API.
- **Admin → Roles** — RBAC is real on the backend, but there's no read/edit
  endpoint; the custom-role editor is Tier 2.
- **Admin → Appearance / Site settings** — no settings-persistence API; AI/SMTP
  are deferred.
- **Admin → Plugins** — the module loader is real but exposes no HTTP list/toggle;
  the enable/disable admin UI is deferred.
- **Notifications** (topbar panel) and **Profile → notification preferences** —
  no personal-inbox backend.
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
- **Persisted theme** — the light/dark choice is saved to `localStorage`.
- **Responsive shell** — the sidebar becomes an off-canvas drawer under `md`
  (hamburger in the topbar).
- **Timestamps** read as UTC via `lib/datetime` (the backend also now serializes
  aware UTC through the `UtcDateTime` column type).

## Placeholder data

All lives in `frontend/src/lib/placeholder-data.ts`, clearly labelled. Every
consumer is one of the "not wired" surfaces above. Deleting that file should
only affect placeholder screens.
