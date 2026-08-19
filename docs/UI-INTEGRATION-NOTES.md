# UI Integration Notes — Flagpost design handoff

This records what happened when the **Flagpost UI handoff** (a full-product
HTML/CSS mock from Claude Design, spanning every tier) was integrated into the
real Next.js frontend.

The mock is a single-page prototype of the *whole* product vision — dashboard,
challenges, scoreboard, participants, support, analytics, automations, a full
admin console, notifications, per-competition theming, drag-and-drop dashboard
widgets. The shell and every section were built. At handoff, only the sections
with a real backend were wired; the rest rendered as faithful UI seeded with
placeholder data and flagged in-app with a "Preview — …" banner. **Every section
is now wired** (see below), so that scaffolding — the banner component and
`placeholder-data.ts` — has since been removed.

**Status: every surface in the mock is wired, and the platform has shipped
through v1.4.0.** The tables below are kept
current, so they double as a map of
which hook and module back each screen — but this document is fundamentally a
*record of the handoff*, not the feature list. For what the platform does today,
read `README.md`; for what's next, `ROADMAP.md`.

Since the original handoff the backend caught up through every tier
(per `claude_plans/phase_3.md`): the notification bell (Phase 0), the whole
automation surface — rules + the visual builder (Phases 1–3), feedback / surveys
(Phase 4), challenge & team analytics (Phase 5), **dashboard customization** —
drag-reorder / resize / show-hide edit mode (Phase 6), **collaborative CRDT
notes** — a team challenge scratchpad + staff ticket notes (Phase 7), and
**guided first-run empty states** — a reusable `EmptyState` across
challenges/scoreboard/support/feedback + a manager dashboard getting-started
guide (Phase 8) — are all real. The **Phase 9** pre-release tranche and the
**Phase 10** four-stage pre-public pass (accessibility / bug / optimization /
security) then wired every last placeholder — Admin → Users, Admin → Dashboard
global stats, Admin → Site settings (operational), per-user notification
preferences, and the per-competition module toggle (now on Competition Settings
→ Modules; the old Admin → Plugins page was removed) — and `placeholder-data.ts`
was deleted. The tables below are kept current.

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
  `components/app/section-header.tsx` (`SectionHeader`; the handoff's
  `NotWiredNote` "Preview" banner was removed once every section was wired).
- Theming is site-wide (Tier 2 Phase 4, §9): an admin sets the default palette +
  accent (Admin → Site settings → Appearance), stored in a SiteSettings singleton and read
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
| Sign in / Register / brand lockup | **Wired** (existing auth hooks). Identity is **username-primary** (Tier 3 Phase 9, ADR-0015): the display name is the case-insensitive-unique login identifier and **email is optional**. Login field is "Username or email" (`identifier`); register/admin-create relabel the name field "Username" and make email optional. |
| Topbar competition switcher | **Wired** (`useCompetitions`, active id in the auth store) |
| Challenges — browse grid + category chips | **Wired** (`useChallenges`, `useCategories`) |
| Challenges — detail dialog (title/points/category/description) | **Wired** (description rendered read-only via `richTextToPlain`) |
| Challenges — flag submission + solve state | **Wired** (Phase 6 — `useSubmitFlag`, solved/solve_count badges, first-blood) |
| Challenges — "Manage challenges" authoring (CRUD, categories, publish, attachments) | **Wired** (reuses `ChallengeAdmin`) — incl. **dynamic scoring** (Phase 9): scoring-type selector + min/decay fields; cards/dialog show the current decayed `value` with a "dynamic" marker; **scheduled release** (`release_at` datetime field + "scheduled" row marker) |
| Challenges — solver list ("who solved this") | **Wired** (Phase 9) — `useChallengeSolves` renders a Solves (N) section in the dialog, first-blood marked |
| Challenges — connection info | **Wired** (#262) — optional free-form address on the authoring form (`connection_info`, ctfcli-compatible); shown in the competitor's challenge dialog as a copyable mono chip, linkified for `http(s)` URLs. Withheld server-side while a challenge is locked |
| Challenges — prerequisites / tags / difficulty / bulk YAML | **Wired** (Phase 9) — prerequisite picker + locked states; per-competition tag/difficulty vocab (settings `VocabEditor` + editor pickers + card chips); Export/Import (ctfcli zip) buttons on Manage challenges (`useExportChallenges`/`useImportChallenges`) |
| Scoreboard — live rankings | **Wired** (Phase 7 — `useScoreboard`: REST initial load + WebSocket room updates, first-frame auth, backoff reconnect). **Freeze** (Phase 9): a "Frozen" badge for all + a staff Freeze/Unfreeze button (`scoreboard_freeze`, `useFreezeScoreboard`) |
| Announcements — post + live banner + dashboard widget | **Wired** (Phase 8 — `useAnnouncements`: REST + WS room, `NewAnnouncementDialog`) |
| Hints — reveal (competitor) + authoring (editor) | **Wired** (Phase 9 — `useHints`: reveal-on-request with cost, hidden body until revealed; scoreboard deducts cost live) |
| Participants — team mode (create/join/leave, browse teams) | **Wired** (reuses `TeamPanel`) |
| Participants — individual mode (competitor roster + standing) | **Wired** (Tier 3 Phase 9) — `GET /participants` lists Participant-role holders with join time / solves / rank / points (reusing the scoreboard computation); `ParticipantsPanel` shows a "your standing" summary + the roster (`use-participants`). Judges (`score_override`) get a **Create award** button → `AwardDialog` (multi-select recipients, title/description/points) posting `POST /awards`; award points fold into the scoreboard |
| Settings → Modules (module enable/disable) | **Wired** (Tier 3 Phase 9, §11.3) — on **Competition Settings** (module state is per-competition, so it lives with the competition's config, not the global Admin section): the full inventory — required-core locked "always on", optional toggleable via `GET`/`PUT /api/competitions/{id}/modules`, gated on `edit_competition` (`use-modules`, `ModulesPanel`). Disabling a module also drops its nav entry (see role-aware navigation) |
| Competition Settings | **Wired** (`CompetitionSettingsForm` on the active competition) |
| Admin → Competitions (list + New + Clone + Archive + Delete) | **Wired** (`useCompetitions`, `CreateCompetitionDialog`). Tier 3 Phase 9: per-row **Clone** (name-prompt dialog, deep-copies a baseline's config), **Archive/Unarchive** (reversible soft-close via `archived_at` — archived competitions drop from the switcher/lobby and are badged here), and **Delete** (hard-delete behind a confirm, `delete_competition`) — `useCloneCompetition`/`useArchiveCompetition`/`useDeleteCompetition` |
| Profile — change password | **Wired** (new `authApi.changePassword` + `useChangePassword`) |
| Lobby — join public / join by code | **Wired** (pre-Tier-2 — `useJoinCompetition` / `useJoinByCode`; refetches permissions so the nav leaves the lobby) |
| Role-aware navigation | **Wired** (pre-Tier-2 — `useAccess` off `/me/permissions` gates manager-only nav + the Admin section; direct admin URLs are guarded). Tier 3 Phase 9: also **module-aware** — an optional module disabled for the active competition drops its nav entry (`GET /modules/enabled`, member-readable) |
| Admin → Event log | **Wired** — audit-log viewer over every emitted event (§3.3), gated on `view_audit_log`; GitLab-style filtering by event/competition/team/actor/time/free-text, pagination, expandable payloads (`use-audit-log`). Tier 3 Phase 9: team/actor filters are **name-autocomplete pickers** (`EntityCombobox`) instead of raw-id inputs |
| Dashboard | **Wired** (Tier 2 Phase 1 + Tier 3 Phase 6) — widget-registration architecture (§10.1) off `dashboard` module endpoints: manager stats/recent-solves/challenge-health/support-queue, participant standing/solves, announcements. Managers (`customize_dashboard`) get an **edit mode** (§10.2–10.5): drag-reorder, per-widget size-cycle, show/hide, save / cancel / reset-to-default, persisted per-user in `dashboard_layouts` (`use-dashboard`, `DashboardGrid`) |
| Support tickets | **Wired** (Tier 2 Phase 2) — `tickets` module: competitor create/reply, staff assign/resolve/internal-notes, ownership scoping; live thread + staff-queue WS rooms with the §4.4 audio cue (`use-tickets`) |
| Presence indicators | **Wired** (Tier 2 Phase 3, §4.1) — WS presence with debounced clear: "N others viewing" on the challenge dialog (new presence-only `challenge` room) and "a judge is looking at this ticket" on the ticket thread (`usePresence` + `PresenceIndicator`) |
| Admin → Site settings → Appearance (site-wide theming + branding) | **Wired** (Tier 2 Phase 4 §9; **custom logo** added Tier 3 Phase 9) — platform name + palette + accent (preset or custom hex) with live preview, plus a **custom org logo** (upload/replace/remove) and a `show_wordmark` toggle; `manage_site_settings`-gated `site_settings` module. Logo bytes live in the DB (a `deferred` blob on the singleton) and stream from a public `GET /site-settings/logo` (nosniff + sandbox CSP); the public read carries `logo_url` + `show_wordmark`, so login/register/sidebar brand from it (`Lockup` gained `logoUrl`/`showWordmark`; `use-site-settings` absolutizes `logo_url`). A **mandatory** "Powered by Flagpost" footer (`PoweredByFooter`) renders on every page so attribution survives a full rebrand (`use-site-settings`, `lib/theme.ts`) |
| Admin → Roles (custom role editor) | **Wired** (Tier 2 Phase 5, §7.4) — `roles` module gated on `manage_roles`: list + permission catalog, create/clone/edit/delete custom roles, assign(by-email)/unassign; system roles read-only, last-admin guard (`use-roles`) |
| Admin → Site settings (operational) | **Wired** (Tier 3 Phase 9) — registration policy (`registration_open`; closed → `/register` 403 + hidden link) and SMTP config for the `send_email` action (`GET`/`PUT /site-settings/operational`, `manage_site_settings`; password write-only). The mailer resolves SMTP from the DB (env fallback). AI stays unbuilt (v1.4.0, #98); **SSO shipped** as its own Auth tab — see below (`use-site-settings`). Plus **platform export / import** (`BackupPanel`, ADR-0016): section-checkbox export → JSON download, additive import from a file → per-table created/skipped summary; `POST /site-settings/export`+`/import`, `manage_site_settings`-gated |
| Admin → Dashboard (site overview) | **Wired** (Tier 3 Phase 9, §6.3) — cross-competition oversight gated on `view_global_analytics`: platform totals (accounts / competitions / teams / challenges / solves) + a per-competition **health** table (status / participants / challenges / solves / open tickets) off `GET /api/admin/overview` (`use-admin-overview`) |
| Admin → Users (account directory + lifecycle) | **Wired** (Tier 3 Phase 9, §7) — `users` module: directory + search (`view_all_users`), create / edit(+password) / soft-ban / unban / hard-delete (`manage_users`). Ban = `User.is_active`, enforced at the auth dependency + login + refresh, revokes sessions; can't ban/delete yourself or the last admin. Role *assignment* stays on Admin → Roles (`use-users`, `UserFormDialog`) |
| Notifications (topbar bell) | **Wired** (Tier 3 Phase 0, §4.4) — real per-user inbox: `notifications` required-core module, `/ws/user/<id>` live push, list/mark-read/read-all; ticket events routed like the audio cue (`use-notifications`). **Per-user preferences wired** (Phase 9): `GET/PUT /api/notifications/preferences` — in-app category mutes (tickets / automations, gated in `create_notifications`) + browser & sound delivery hints (client-honored via `lib/notification-prefs`) |
| Automations (competition + admin) | **Wired** (Tier 3 Phases 1–3, §5) — the `automations` optional module + engine (nine §5.3 actions incl. `open_survey`, per-competition toggle, plus the time-based `competition.time_remaining` trigger via a scheduler) and the §5.5 **visual rule builder**: catalog-driven When→If→Then editor for competition + global rules, plus a personal notify-self section (`use-automations`, `rule-builder`) |
| Feedback / surveys | **Wired** (Tier 3 Phase 4, #22) — the `feedback` optional module: staff survey builder (5 question types, reorder, open/close), competitor response form, results dialog (histograms/tallies/text) + CSV export; a submission emits `survey.submitted`, a live automation trigger (`use-feedback`) |
| Analytics | **Wired** (Tier 3 Phase 5, #23) — the `analytics` optional module (staff, `view_competition_analytics`): overview + per-challenge table (solves / attempts+fails / completion rate / avg solve time / hints / linked tickets) and a competitors/teams ranking (rank / points / solves / first bloods / tickets / last solve), read off existing submission data (`use-analytics`) |
| Collaborative notes | **Wired** (Tier 3 Phase 7, §4.2, ADR-0014) — the required-core `collab` module: a **team per-challenge scratchpad** in the challenge dialog and **staff notes** on a ticket thread, both live-collaborative rich text (Y.js under TipTap over a `note/<doc_key>` WS room, dumb-relay transport + blob persistence). Scoped per-request — team membership / `ticket_view_internal_notes` (`CollabNote`, `lib/collab`). v1.1.0 added a **personal** `user_challenge:` scope so individual-mode competitors get the same surface (#47) |

### Added after the handoff (v1.1.0 – v1.4.0)

Surfaces with no counterpart in the original mock, listed so the table stays a
complete map of the app.

| Section | Status |
| --- | --- |
| Live updates across the site | **Wired** (v1.1.0, #18) — a per-competition `activity` WS room fans id-only pings from a curated §3.2 event allowlist; pages refetch their own permission-filtered slice rather than trusting a pushed payload. Keeps the analytics insight cards, challenge grid and ticket lists live for free |
| Sortable / searchable / paginated tables | **Wired** (v1.1.0, #16 #17 #20) — a headless data-table layer (`lib/data-table`, `use-data-table`, `components/ui/data-table`) rolled out across the table and card surfaces |
| Public spectator board | **Wired** (Phase 9 + v1.1.0 #24) — a standalone `/public` directory + `/public/[competitionId]` board **outside** the app shell and outside auth, per-competition opt-in. v1.1.0 added insight cards and a live cumulative-points timeline (`usePublicScoreboard`, `utils/public_insights`), all computed under the board's own freeze cutoff so the page can't leak what the board hides |
| Announcements — severity + targeting | **Wired** (v1.1.0, #44) — info/warning/critical severity and an audience (whole competition, or chosen teams/users), with a bell notification per recipient. Targeted announcements never touch the shared room; they go over each recipient's `/ws/user/<id>` room, and the join snapshot is filtered identically |
| Admin → Site settings → Auth (identity providers) | **Wired** (v1.2.0, #58, ADR-0021; generalized by ADR-0022) — the `sso` required-core module: CRUD over site-wide `IdentityProvider` rows (kind + trust posture + per-kind config) at `/api/admin/auth-providers`, gated on `manage_auth_providers` (deliberately *not* `manage_site_settings`). Login renders a provider button per enabled redirect-kind row; `/auth/callback` completes the code exchange. The settings page admits either permission and hides tabs the holder lacks |
| Profile — API tokens | **Wired** (v1.2.0, #75) — self-service mint/list/revoke (`ApiTokensCard`); the raw `flp_…` token is shown exactly once. Admin → Users carries the oversight panel (`manage_api_tokens`: list every token on the platform, revoke any) |
| Profile — email card + verification | **Wired** (v1.2.0, #74/#106) — add / change / clear your own email behind your current password and a 5-per-5-min limit; a change clears verification and re-triggers it. `/verify-email` completes a mailed link; the lobby carries an unverified prompt |
| Rules / code of conduct | **Wired** (v1.2.0, #57) — site-wide text with an optional per-competition override, authored on Admin → Site settings and Competition Settings. `RulesAcceptModal` gates all four join paths (checkbox-gated Accept, or Continue when the document is display-only); acceptance is recorded, and changing the document resets it |
| Analytics → Submissions | **Wired** (v1.2.0, #76) — a staff dispute-resolution tab: filterable, paginated raw submissions with CSV export, behind its own `view_submissions` permission (`SubmissionsBrowser`, `use-submissions`) |
| Support tickets — screenshots | **Wired** (v1.2.0, #80, §13.3) — `ScreenshotPicker` stages images on a message, `TicketAttachments` renders thumbnails into a lightbox. Bytes stream through the API and render from a `blob:` URL (the CSP blocks a cross-origin storage URL in an `<img>`); an attachment on an internal note inherits that note's visibility |
| Update notice | **Wired** (v1.2.0, #111) — an admin-only banner when a newer release exists, dismissible per version, plus a "last checked" line on Admin → Site settings. Gated at the *query*, not just the render, so a competitor never calls the admin endpoint |
| First-run setup wizard | **Wired** (Phase 9, ADR-0017) — `/setup`, outside the shell: creates the owner account and initial branding on an install that has no administrator. `SetupGuard` redirects to it while unconfigured |
| Password reset | **Wired** (Phase 9, Group D) — `/forgot-password` + `/reset-password`, both outside the shell (`useForgotPassword`/`useResetPassword`) |
| Auth providers — SAML & LDAP | **Wired** (v1.3.0, #100/#101, ADR-0022) — the Auth tab's provider form grows two more `kind`s on the same `/api/admin/auth-providers` CRUD: **SAML 2.0** (IdP entity/SSO/cert + SP metadata URL, another "Sign in with…" redirect button) and **LDAP / AD** (server/bind/base/attribute fields, forced-closed posture, **no** login button — it rides the ordinary username/password form). The public button list excludes LDAP by kind |
| Restrict external sign-in (trust posture) | **Wired** (v1.3.0, #118, ADR-0022) — each provider carries an `open`/`closed` posture on the Auth form: public IdPs stay behind the registration + email-domain gate, admin directories are admitted by being enabled, with an `email_is_authoritative` opt-in for email linking |
| Alternative challenge list view | **Wired** (v1.3.0, #55) — a compact list alternative to the card grid, toggled and remembered per user (`stores/challenge-view`, `ChallengeList`) |
| Venue / projector mode | **Wired** (v1.3.0, #77) — a big-screen public view for live events (scoreboard, first-blood splashes, insight cards) under `/public`, outside the app shell (`components/public/venue`) |
| Tabbed profile page | **Wired** (v1.3.0, #113) — `/profile` reorganised into tabs (account incl. email + password, notifications, API tokens) the way Admin → Site settings is, with the active tab in `?tab=` |
| AI assistants | **Wired** (v1.4.0, #98, ADR-0023) — the optional `ai` module: an **administrator assistant** and an audience-aware **competitor assistant** over an operator-configured OpenAI-compatible provider, configured on Admin → Site settings → AI. Ships **inert** (`ai_settings.enabled` off by default); admin transcript oversight behind `ai_view_transcripts` |
| Automations builder polish | **Wired** (v1.4.0, #210/#211/#212) — the visual rule builder's condition rows show human field labels (not raw keys) in roomier inputs, and id action/condition params are picked from **searchable name dropdowns** (challenge/survey/hint), never raw ids |
| Hints — hidden / scheduled release | **Wired** (v1.4.0, #213) — the challenge editor's hints section grows a "Hidden until released" toggle + optional release time and a Publish button, so a hint can be authored hidden and released later (manually, on a schedule, or by the `publish_hint` automation) |
| Sign-in personalization | **Wired** (v1.4.0, #195/#197) — admin-selectable **animated sign-in backgrounds** (Aurora/Gradient/Constellation) and a **custom rich-text sign-in notice** above the login card, both on Admin → Site settings → Appearance |
| Built-in Google / Microsoft sign-in | **Wired** (v1.4.0, ADR-0024) — one-click OIDC provider presets on the Auth tab that prefill Google and single-tenant Microsoft Entra, with the official brand mark on the login button |
| Mass CSV user import | **Wired** (v1.4.0, #171) — Admin → Users bulk-creates accounts from a CSV with optional role assignment |
| Venue mode — responsive scaling | **Wired** (v1.4.0, #214) — the projector view now scales to the display (fluid root + em sizing) so a large screen fills instead of showing laptop-sized boxes |

## Formerly UI-only (now wired or deferred)

At handoff these rendered as placeholder UI. All are now resolved — wired to a
real backend, or the underlying feature deferred with the placeholder UI removed.
**No placeholder data remains anywhere in the app.**

- **Dashboard** — now fully wired *and customizable* (Tier 2 Phase 1 + Tier 3
  Phase 6, see the wired table above). The widget-registration architecture that
  shipped as a fixed layout made the drag-and-drop customization layer additive,
  exactly as intended (§10.2) — it's now built for the manager dashboard.
- **Admin → Site settings — AI / SSO / integrations** — the mock's single
  catch-all panel became a tabbed page (#104): **General** (registration policy,
  data retention, update checks), **Email** (SMTP), **Auth**, **Rules**,
  **Backup**, **Appearance**, **AI**. **SSO shipped in v1.2.0** on the Auth tab,
  gated on its own `manage_auth_providers` permission (#58, ADR-0021). **AI
  shipped in v1.4.0** (#98, ADR-0023): the AI tab now carries the provider config
  (OpenAI-compatible endpoint, model, write-only key, per-assistant system
  prompts) behind the `ai_settings.enabled` master switch, and the two assistants
  render in-app once an admin configures and enables it.

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
  default + accent are set by an admin on Admin → Site settings → Appearance (Tier 2 Phase 4).
- **Responsive shell** — the sidebar becomes an off-canvas drawer under `md`
  (hamburger in the topbar).
- **Timestamps** read as UTC via `lib/datetime` (the backend also now serializes
  aware UTC through the `UtcDateTime` column type).

## Placeholder data

None left — `frontend/src/lib/placeholder-data.ts` was **deleted** in Tier 3
Phase 9 once its last consumers (the Admin → Dashboard global stats/module
health and the Admin → Users directory) were wired to real endpoints. Every
section listed above now reads live data; the remaining "not wired" surfaces are
feature gaps (no fake data), not placeholder screens. The **AI** tab on Admin →
Site settings was the last stub; it wired up when the AI module shipped in
v1.4.0 (#98, ADR-0023).
