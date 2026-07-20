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
| Participants — team mode (create/join/leave, browse teams) | **Wired** (reuses `TeamPanel`) |
| Competition Settings | **Wired** (`CompetitionSettingsForm` on the active competition) |
| Admin → Competitions (list + New competition) | **Wired** (`useCompetitions`, `CreateCompetitionDialog`) |
| Profile — change password | **Wired** (new `authApi.changePassword` + `useChangePassword`) |
| Lobby — public competitions list | **Wired** (filtered from `useCompetitions`) |

## Built as UI, NOT wired (placeholder data + in-app "Preview" banner)

These need features that are still on the roadmap. UI is in place so they're not
a retrofit later; **none of the data is real**.

- **Dashboard widgets** (stats, activity, announcements) — needs scoring /
  announcements / WebSocket endpoints. Ships as a **fixed layout**; the mock's
  drag-and-drop customization is explicitly deferred (ROADMAP).
- **Scoreboard** — Tier 1 Phase 7 (ranking computation + live WebSocket layer;
  the submissions data it ranks from exists as of Phase 6). The name column
  does reflect the real participation mode.
- **Support tickets** — Tier 2.
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

- The mock's **"Preview as (demo)" role switcher** and role-based nav gating.
  The backend doesn't surface the current user's role/permissions on `/me` yet,
  so — per the agreed approach — every signed-in user currently sees all nav.
  Real RBAC gating is a follow-up once `/me` (or a `/me/permissions` endpoint)
  returns the caller's effective permissions.
- **Per-competition theming** override examples (Tier 2) — the token layer
  supports it, but no competition-scoped theming UI was built.

## Placeholder data

All lives in `frontend/src/lib/placeholder-data.ts`, clearly labelled. Every
consumer is one of the "not wired" surfaces above. Deleting that file should
only affect placeholder screens.
