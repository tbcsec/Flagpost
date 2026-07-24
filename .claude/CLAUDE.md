# CLAUDE.md

## What this project is

Flagpost — a modern, open-source CTF competition management platform.
Product rationale lives in `docs/VISION.md`. Technical design lives in
`docs/ARCHITECTURE.md` and is binding, not aspirational — if code and
`ARCHITECTURE.md` disagree, that's a bug in one of them, not a judgment
call to make silently.

## Read these before you start — don't duplicate them here

- `docs/VISION.md` — what and why.
- `docs/ARCHITECTURE.md` — how. 15 sections; check the relevant one
  before designing anything new (event bus, RBAC, tenancy, automation,
  and the module system each have a section — don't reinvent a pattern
  that's already specified).
- `docs/ROADMAP.md` — build order, in tiers. Check which tier is current
  before starting new work.
- `docs/adr/` — why past decisions were made the way they were. Check
  before proposing an alternative to something already decided. If an
  ADR's decision looks wrong given what you're building, say so and
  propose a new ADR — don't quietly work around it.

If something in this file conflicts with those three, they win. Fix this
file, don't ignore it.

## Current build stage

<!-- Update this line as tiers/phases complete. -->
**Tier 0, Tier 1, and Tier 2 ("Makes It Good") are all complete — Tier 2 was
built phase-by-phase per `docs/claude_plans/phase_2.md` (Phases 0–5 all
shipped). Tier 3 is the current tier and is now scoped/planned in
`docs/claude_plans/phase_3.md` (Phases 0–10; **Phases 0–8 shipped**, Phase 9 —
an **owner-inserted ad-hoc phase** of pre-release features & cleanup — is the
current one (built item-by-item, **one push at the end**), and Phase 10 —
accessibility / responsiveness / optimization pass — is the final phase before
initial public release).
An owner revision pulled three previously-deferred subsystems up into Tier 3 —
the **full automation engine** (§5), **dashboard drag-and-drop** (§10), and
**collaborative rich-text/CRDT editing** (§4.2) — alongside the polish items
(feedback/survey, analytics, onboarding, a11y). Build order is **automation
engine first** (full spec), then the rest; work the phases in order and don't
start a phase without confirming scope.** See `docs/ROADMAP.md` for the tier
breakdown and `phase_3.md` for the phase-by-phase plan.

What's built:

- **Tier 0** — the async event bus (§3) with an audit-log consumer, JWT
  auth + roles/permissions-as-data (§7), the Competition tenancy root (§6),
  the Tailwind v4 `@theme` token layer + shadcn primitives (§9), and the
  TanStack Query hook + Zustand store layer (§8).
- **Tier 1** — the manifest-driven module loader (§11.1); competition
  admin (edit/schedule/visibility); teams; challenges + categories; MinIO
  file attachments; flag submission + static-points scoring; the WebSocket
  layer (§4.1) with a live scoreboard; announcements; and hints. The full
  authenticated app shell (sidebar + topbar) from the design handoff is
  wired — see `docs/UI-INTEGRATION-NOTES.md` for what's real vs. still
  placeholder.
- **Tier 2 Phase 0** (pre-Tier-2 gap fixes) — competition join (public
  self-serve + invite code; the only way into an individual-mode
  competition), enforced competition visibility, role-aware navigation via
  `GET /api/auth/me/permissions`, tz-aware timestamps, an admin
  **audit-log / event viewer** (its own required-core module) with
  GitLab-style filtering, and UI polish (toasts, skeletons, scoreboard
  medals, solve celebration, persisted theme, responsive drawer).
  `change-password` now emits `user.password_changed`.
- **Tier 2 Phase 1** — the judge/admin **operational dashboard** (§10) on a
  widget-registration architecture: a registry of self-contained,
  size-declaring widgets (`lib/dashboard/registry.tsx`) rendered in a fixed
  per-role layout, so the (deferred) drag-and-drop layer is additive later,
  not a rewrite. Backend stats/recent-solves/challenge-health/me endpoints
  in a required-core `dashboard` module.
- **Tier 2 Phase 2** — **support tickets** (§4.4), a required-core `tickets`
  module: competitor create/reply, staff assign/resolve/internal notes,
  ownership-scoped reads, a live per-ticket WS thread + a staff support
  queue room, and the one sanctioned **audio cue** for new tickets/replies.
  Registers a support-queue dashboard widget into Phase 1's registry.
- **Tier 2 Phase 3** — **presence** (§4.1) on the WS layer: a room type opts
  in with a `presence_member` builder and the connection manager tracks a
  per-user, tab-deduped "who's here" set, broadcasting it on change with a
  debounced clear (`ws_presence_grace_seconds`) so brief reconnects don't
  flicker. WS-level state only — no event, REST, or migration. Drives "N
  others viewing" on the challenge dialog (a new presence-only `challenge`
  room) and "a judge is looking at this ticket" on the Phase 2 ticket room.
  Frontend: `usePresence` + `PresenceIndicator`.
- **Tier 2 Phase 4** — **site-wide theming** (§9), a required-core
  `site_settings` module: a **SiteSettings singleton** (platform name +
  default palette + accent), public `GET` (login/register brand before auth) +
  `manage_site_settings`-gated `PUT` emitting `site.settings_updated`.
  Curated palette presets (**Harbor/Eclipse/Umbra** dark, **Daybreak/Sandstone**
  light — a palette is a full token set, not a free-form background picker);
  accent is one hue overriding only `--primary`/`--ring` (+ YIQ-chosen
  foreground), preset or custom hex, never touching `--success`/the logo
  (LOGO-SPEC §7). `lib/theme.ts` (registry + colour math) + a `ThemeApplier`
  (palette = per-user override ?? site default; no-flash inline script) + the
  topbar palette menu + the wired Admin → Appearance page. System roles now
  **re-sync from the permission catalog on every startup** (`seed_system_roles`)
  so a newly-added permission reaches an already-migrated Administrator.
- **Tier 2 Phase 5** — **custom role editor** (§7.4), a required-core `roles`
  module gated on `manage_roles`: list roles + the categorized permission
  **catalog**, create/clone/edit/delete **custom** roles, and
  list/assign(by-email)/unassign assignments. Invariants: system roles are
  read-only (clone to vary), assignment scope matches the role, no deleting an
  assigned role, no unassigning the last Administrator. Emits
  `role.created`/`updated`/`deleted`/`assigned`/`unassigned`. Frontend: the
  wired Admin → Roles page (matrix editable for custom / read-only for system;
  competition roles hide global permissions) + `use-roles.ts`. No migration —
  the role/assignment tables are Tier-0.
- **Tier 3 Phase 0** (automation groundwork) — the **event-dispatch split**
  (ADR-0012, supersedes ADR-0009): `emit()` awaits foreground handlers (audit +
  WS broadcasts, the default) but schedules `background=True` handlers
  fire-and-forget so a slow webhook/email handler can't block the request — the
  lane the automation engine's webhook/email actions use. Plus the real **§4.4
  in-app notification center** (was placeholder): a `notifications` required-core
  module with a per-user `Notification` model, `GET/mark-read` REST, the
  `/ws/user/<id>` room, and ticket-event listeners that notify staff/opener the
  same way the audio cue routes; `use-notifications.ts` + the wired topbar bell.
  `auth.deps.users_with_permission` (the "who can do X here" audience query).
- **Tier 3 Phase 1** — the **automation engine** (§5), the first genuinely
  **optional** module (`automations` — per-competition toggle via
  `competition_modules` + `PUT /api/competitions/{id}/modules/{module_id}`,
  kernel-mounted; disabled = nothing fires for that competition's events and
  the org-rules API 404s). `AutomationRule` per §5.1 (`trigger_type` = verbatim
  §3.2 event name, validated against `utils/event_catalog.py`; conditions
  AND-ed; global rule = null competition, needs a *global* automation grant;
  personal rules = **notify-self only**, no perms needed). Engine
  (`utils/automation_engine.py`) runs on the ADR-0012 background lane with two
  loop guards (automation.* never triggers; cascade-depth cap). **All eight
  §5.3 executors** (`utils/automation_actions.py`): notify / send_email
  (aiosmtplib, no-op unconfigured) / webhook (basic — §5.4 hardening is
  Phase 2) / release_hint (free, emits `hint.released`) / unlock_challenge /
  create_ticket / update_score (`ScoreAdjustment` folded into the scoreboard)
  / create_award (`Achievement` — renamed from `award_achievement` in Phase 9,
  now carries scoreboard points). Reserved `automation_*` perms flipped
  live; Judge gained them. Frontend: `use-automations.ts` + minimal rules list
  on `/automations` (toggle/delete; builder is Phase 3).
- **Tier 3 Phase 2** — **webhook hardening** (§5.4, ADR-0013) in
  `utils/webhook_security.py`, applied by the `webhook` executor: per-call
  **SSRF blocklist** (resolve host, reject any non-routable IP incl. the
  `169.254.169.254` metadata endpoint + IPv4-mapped IPv6; refuse unresolvable;
  `follow_redirects=False`), **header stripping** (Authorization/Cookie/Host/
  X-Forwarded-*/content-*), and **content-type escaping + chat-token defang**
  (Discord `@everyone`, Slack `<!…>`/`<@…>`, markdown links) of the values
  substituted into an optional `body_template`. Residual/open: resolve→connect
  TOCTOU + destination rate-limiting (§15). No migration; backend-only.
- **Tier 3 Phase 3** — the **visual rule builder** (§5.5): a catalog-driven
  node-flow (When→If→Then) editor. `GET /api/automations/catalog`
  (`utils/automation_catalog.py`) now describes triggers + their payload fields,
  operators (`unary` flag), and each action's config fields (UI `kind`) — so a
  new action is backend-only and the UI follows (drift test guards it).
  `components/automations/rule-builder.tsx` + pure serialization in
  `lib/automation-builder.ts` (unit-tested). Lives on `/automations` (competition
  rules + a personal notify-self section); Admin → Automations hosts global
  rules. No migration; the builder is additive over the Phase-1 engine/schema.
  **Trigger authorization** (§5.1): `TRIGGER_PERMISSIONS` maps each event to the
  permission that governs observing it; org-rule create/update enforce it and the
  `/catalog?competition_id=` trigger list is filtered to match — so a Judge
  can't automate on `role.assigned` etc. (personal rules are safe by the
  owner-caused invariant, so they skip the check).
- **Tier 3 Phase 4** — **feedback / surveys** (ROADMAP #22): the `feedback`
  optional module (the **second** one — shares the per-competition toggle with
  `automations`; routes 404 when disabled). `Survey` + `SurveyQuestion`
  (rating_1_10/rating_1_5/short_text/long_text/multiple_choice) + per-**user**
  `SurveyResponse`/`SurveyAnswer` (+ migration). Staff build/reorder/open
  surveys and read results + **CSV export** (`feedback_manage` /
  `feedback_view_responses`); competitors answer open ones once
  (`feedback_submit`), emitting **`survey.submitted`** (a live automation
  trigger; renamed from `feedback.submitted` in Phase 9 to sit in the
  `survey.*` namespace). Marking a survey open emits **`survey.opened`** (another trigger).
  New §7.1 Feedback perms (Judge gets all, Participant gets submit).
  Frontend: gated **Feedback** nav → `/feedback` (survey editor, response form,
  results dialog), `use-feedback.ts`.
- **Tier 3 Phase 4 automation glue** (owner ask) — closes the loop between
  feedback and automations: the **`open_survey`** action (§5.3, marks a survey
  open + emits `survey.opened`), and the **first time-based trigger**
  **`competition.time_remaining`** — a per-minute scheduler
  (`utils/automation_scheduler.py`, started in the lifespan) fires
  competition-scoped rules once when `minutes_remaining` crosses their threshold
  condition (dedup via `trigger_count`; `run_rule` factored out of the engine so
  the scheduler reuses it). Enables "an hour before the end → open the survey →
  notify participants". No new migration; all catalog-driven (the builder shows
  the new trigger/action automatically).
- **Tier 3 Phase 5** — **challenge & team analytics** (ROADMAP #23): the
  `analytics` **optional module** (third one, per-competition toggleable),
  `utils/analytics.py` + `routers/analytics.py` gated on
  `view_competition_analytics` (staff). `/analytics/challenges` (per-challenge
  solves / attempts+fails / completion rate / avg solve time / hints / linked
  tickets) and `/analytics/teams` (per-subject rank/points/solves/first-bloods/
  tickets-opened/last-solve, reusing `compute_scoreboard`). Pure read model off existing submission/hint/
  ticket data — **no migration**; timestamp math in Python for SQLite/Postgres
  parity. Frontend: wired `/analytics` page (overview + two tables),
  `use-analytics.ts`. `view_global_analytics` (cross-site rollup) stays unbuilt
  (§6.3 consolidation deferred).
- **Tier 3 Phase 6** — **dashboard drag-and-drop** (§10.2–10.5, ROADMAP #26):
  the per-user layer over Tier-2's fixed widget registry (built additive on
  purpose, §10.1). `DashboardLayout` (`dashboard_layouts`, keyed
  `(user_id, dashboard_key)`; **per-user, not competition-scoped** — a personal
  preference, so the competition in the route only scopes the check) + a
  migration. Three endpoints on the existing required-core `dashboard` module —
  `GET/PUT/DELETE .../dashboard/layout?dashboard_key=` gated on
  `customize_dashboard`: GET returns saved layout or **null** (→ code default),
  PUT upserts on exit-edit, DELETE = reset-to-default. Layout JSON is **opaque
  to the backend** (frontend registry owns the widget catalog + legitimate
  sizes; backend does shape/bound validation only — key allowlist, positive
  grid units, ≤50 entries), so a new widget stays a frontend-only change. No
  event (personal pref, like the theme palette override). Frontend:
  `lib/dashboard/layout.ts` (pure `mergeLayout`/`cycleSize`/`toSaved`/`moveEntry`,
  unit-tested), `DashboardGrid` edit mode (**native HTML5 drag-and-drop — no DnD
  library**; per-widget size-cycle + show/hide; Save/Cancel/Reset), layout hooks
  in `use-dashboard.ts`. Managers customize the `manager` dashboard; participants
  keep the fixed default. The grid is an **ordered column-span flow** (CSS reflow),
  not a 2D `{row,col}` engine; `manage_dashboard_widgets` stays Admin-only + unused
  (widget-catalog governance, deferred).
- **Tier 3 Phase 7** — **collaborative rich-text / CRDT editing** (§4.2, ROADMAP
  #27, ADR-0014): the required-core **`collab` module**. Two owner-chosen
  surfaces: a **team per-challenge scratchpad** (challenge dialog, team-facing)
  and **staff notes on a ticket** (ticket thread, staff-facing). One
  `note/<doc_key>` WS room serves both; `doc_key` =
  `team_challenge:<team_id>:<challenge_id>` or `ticket:<ticket_id>`, authorized
  per request by `utils/collab.resolve_note` (team membership; or
  `ticket_view_internal_notes` staff — **not** the ticket opener). **Transport =
  dumb relay + client-snapshot persistence (ADR-0014):** the server relays opaque
  Y.js update frames (`manager.broadcast(exclude=sender)`) and stores one
  full-state blob per doc (`collab_documents`, `LargeBinary` + migration), never
  decoding the CRDT; base64 over the JSON socket. The §4.1 WS router gained an
  `on_message` hook (broadcast-only rooms unchanged; `on_message` opens its own
  DB session only on the debounced persist, keeping the relay hot path DB-free).
  Frontend: `yjs` + `@tiptap/extension-collaboration`, `lib/collab.ts` (Y.Doc ↔
  socket), `lib/ws.ts` `send()` buffering, `<CollabNote>`. A **webpack alias pins
  Y.js to a single instance** (`next.config.mjs`) — its hard singleton
  requirement. No per-cursor awareness; the soft-lock cue reuses the existing
  challenge/ticket presence indicators.
- **Tier 3 Phase 8** — **onboarding / empty states** (ROADMAP #24): a reusable
  **`EmptyState`** primitive (`components/ui/empty-state.tsx`) applied role-aware
  across the first-run surfaces — challenges (staff "Create a challenge" CTA vs
  competitor "check back"), scoreboard, support (competitor New-ticket CTA vs
  staff), feedback (staff "Create a survey" CTA) — plus a manager **`FirstRunGuide`**
  on the dashboard (3-step getting-started card, gone once a challenge is
  published). Frontend-only, no backend. Same commit carried a design tweak:
  **dialog widths +25%** (`components/ui/dialog.tsx` base `max-w-lg`→`max-w-[40rem]`,
  512→640px; override tiers scaled to match) so the collaborative notes get more
  room, and the `CollabNote` editor min-height `min-h-24`→`min-h-32`.
- **Tier 3 Phase 9** (owner-inserted ad-hoc pre-release phase; **not yet pushed**
  — accumulates until the owner signals done) — items so far:
  - **Individual-mode Participants page**: `GET
    /api/competitions/{id}/participants` (`routers/participants.py`, mounted by
    the `competitions` module) — the roster of competition-scoped Participant-role
    holders (§7.5) with join time / distinct-solve count / standing (rank+points
    reused from `compute_scoreboard`); `challenge_view`-gated, competition-scoped,
    no migration/event. Frontend `use-participants.ts` + `ParticipantsPanel`
    replaces the old individual-mode placeholder on `/participants`.
  - **Module management wired**: `GET /api/competitions/{id}/modules` returns the
    full inventory (added `required_core` to `ModuleStateOut` + `all_manifests()`
    loader accessor) — core locked, optional toggleable via `PUT`, gated on
    `edit_competition` (`use-modules.ts` + `ModulesPanel`). Module state is
    **per-competition** (§11.3 — owner reaffirmed over site-wide), so the UI lives
    on **Competition Settings** (`/settings`), not the global Admin section — the
    old `/admin/plugins` page + Admin-nav entry were removed. **Disabled modules
    drop from the nav**: a member-readable `GET /modules/enabled` (`challenge_view`)
    gives the enabled optional-module ids so the shell filters `COMP_NAV` items
    tagged with a `module` (Feedback/Analytics/Automations); shares the
    `["modules", id]` query key so a toggle updates the nav live.
  - **Cleanup**: `suppressHydrationWarning` on the root `<html>` (`app/layout.tsx`)
    silences the no-flash theme script's expected SSR-vs-client `data-palette`
    mismatch.
  - **Admin → Users wired** (was placeholder): new `users` required-core module +
    `routers/users.py` (`/api/users`) — directory/search (`view_all_users`),
    create/edit(+password)/ban/unban/delete (`manage_users`). Soft-ban = new
    `User.is_active` (+ migration) enforced at `get_current_user` (live token
    rejected), login (403), refresh; ban + password-reset revoke refresh sessions.
    Guards: can't ban/delete yourself or the last active Administrator. New §3.2
    `user.created/updated/banned/unbanned/deleted` events (in the event + automation
    catalogs, `manage_users`-governed triggers). Frontend `usersApi` + `use-users`
    admin hooks + wired page (`UserFormDialog`, ban, delete-confirm, self-protected);
    `DIRECTORY_USERS` placeholder removed. Role *assignment* stays on Admin → Roles.
  - **Name references over raw IDs**: reusable `EntityCombobox`
    (`components/ui/entity-combobox.tsx`, dependency-free; shows a name, stores the
    id) replaces raw team/user-id inputs — the event-log Actor/Team filters
    (`useUsers`/`useTeams`) and the automation rule-builder condition values for
    `team_id`/`*user_id` fields (`useTeams`/`useParticipants`, via a new optional
    `competitionId` prop on `RuleBuilder`; global rules keep the plain input).
  - **Clone a competition**: `POST /api/competitions/{id}/clone` (`create_competition`)
    → `utils/competition_clone.py` deep-copies config into a fresh competition
    (new ids/invite code, schedule cleared): settings, categories, challenges
    (incl. stored flag), hints, **attachments** (objects duplicated — added
    `ObjectStorage.get`), **surveys+questions** (closed), module on/off state.
    Clean slate: no participants/scores/tickets/automations/audit. Emits
    `competition.created` (+`cloned_from`). Frontend: `useCloneCompetition` + a
    Clone action + name-prompt dialog on Admin → Competitions. Owner scope:
    attachments + surveys in, automation rules out.
  - **Competition archive + delete**: `POST /competitions/{id}/archive`+`/unarchive`
    (`edit_competition`) = reversible soft-close via new `Competition.archived_at`
    (+ migration) — hidden from the switcher/lobby, badged in the admin list.
    `DELETE /competitions/{id}` (`delete_competition`) hard-deletes the tenant tree
    behind a confirm. New §3.2 `competition.archived/unarchived/deleted` events.
    Frontend: `useArchiveCompetition`/`useDeleteCompetition` + wired Admin page.
  - **Admin → Dashboard wired** (was placeholder): `GET /api/admin/overview`
    (`routers/admin_overview.py`, dashboard module) gated on **`view_global_analytics`**
    (§6.3 cross-competition read, first consumer) — platform totals + per-competition
    health (derived status / participants / challenges / solves / open tickets).
    Frontend `use-admin-overview.ts` + tiles & health table. `lib/placeholder-data.ts`
    **deleted** (all consumers wired).
  - **Admin → Site settings wired** (was placeholder): the operational (non-theming)
    site config. **Registration policy** — `SiteSettings.registration_open`
    (+ migration); closed → `POST /register` 403 (admins mint accounts via Users);
    public `GET /site-settings` carries `registration_open` (login hides Register,
    `/register` shows a closed notice). **SMTP** — `smtp_*` on `SiteSettings`, editable
    via `GET`/`PUT /site-settings/operational` (`manage_site_settings`; password
    **write-only** — GET returns `smtp_password_set`); the `send_email` mailer now
    resolves SMTP from the DB (env fallback). AI stays deferred.
  - **Branded favicon**: `app/icon.svg` (Next.js auto-serves it) — the Flagpost
    mark on a dark brand tile.
  - **Expanded branding — custom logo + mandatory attribution** (extends §9 /
    LOGO-SPEC §7): orgs may replace the built-in mark with their own **logo** while
    Flagpost stays visible. Logo bytes live **in the DB** (a `deferred` `logo_data`
    `LargeBinary` on the `SiteSettings` singleton + `logo_content_type`/
    `logo_updated_at`, migration `b4c5d6e7f8a9`), *not* object storage — so branding
    works infra-free and pre-auth (like the collab snapshot, ADR-0014). Public
    `GET /site-settings` gains `logo_url` (a `/api/site-settings/logo?v=<epoch>`
    path — the model property reads only non-deferred cols, so the settings row
    never drags the blob) + `show_wordmark`. `manage_site_settings`-gated
    `POST`/`DELETE /site-settings/logo` (1 MB cap, PNG/JPEG/WebP/GIF/SVG) store/clear
    it; the **public** `GET /site-settings/logo` undefers + streams the bytes
    defensively (`nosniff` + `Content-Security-Policy: … sandbox` so a
    direct-navigation SVG can't run script — the app renders it via `<img>`, which
    already neuters SVG scripting). The **Admin toggle** `show_wordmark` (on the
    existing appearance `PUT`) hides the platform-name wordmark for logos that bake
    in their name. Frontend: `Lockup` gained `logoUrl`/`showWordmark` (sidebar +
    login + register), `use-site-settings` absolutizes `logo_url` to the API origin
    (`apiAssetUrl`) via a query `select`, `useUploadLogo`/`useDeleteLogo`, and the
    Admin → Appearance Logo section. A **mandatory, non-configurable
    `PoweredByFooter`** ("Powered by Flagpost" → the GitHub repo, built-in mark) on
    every page (app shell + auth screens) keeps attribution even under a full
    rebrand. Reuses `site.settings_updated`; no new event.
  - **Username-primary identity, optional email** (ADR-0015, extends §7.7): the
    **display name is now the primary login identifier** (a username) — required and
    **case-insensitively unique** (functional index `uq_users_display_name_lower` on
    `lower(display_name)` + app-level check; migration `c5d6e7f8a9b0`) — and **email
    is optional** (`User.email` nullable, unique-when-present; multiple NULLs OK on
    both engines). Local login accepts the **display name *or* email**
    (`LoginRequest.identifier`, with an `email` JSON alias for back-compat; matched
    case-insensitively, email-then-name via `auth/identity.py`
    `find_by_identifier`/`display_name_taken`/`email_taken`, shared by register +
    admin create/edit). `UserOut`/`UserAccountOut`/`AssignmentOut.user_email` all
    nullable; Admin → Roles assign resolves by **email or username** so email-less
    accounts stay assignable. Frontend: login field "Username or email"
    (`identifier`), register/admin-create email optional + display-name relabelled
    "Username", `.email` render sites null-guarded. Two owner calls (via question):
    reuse display name as the username (not a separate handle), case-insensitive.
    No new event (reuses `user.registered`/`user.created`).
  - **Platform export / import** (ADR-0016) — a **full-fidelity, section-selectable
    backup** on Admin → Site settings. `utils/backup.py` is a **generic engine**: a
    column (de)serialiser (datetimes→ISO, `LargeBinary`→base64, deferred cols
    `undefer`-ed on export) + a declared `SPECS` registry (per-table FK-remaps,
    import order, natural keys). One versioned JSON document keyed by table.
    **Sections** (checkboxes): `site_settings`, `users`, `roles`, `competitions`,
    `automations`, `audit_log`. **Import is additive** (owner call) — creates
    missing rows, never modifies/deletes: top-level entities skip by natural key
    (user by name/email, role/competition by name), a **competition is atomic**
    (whole subtree skipped if its name exists), new ids minted + all FKs rewritten
    through id maps (required-ref miss skips the row, optional nulls it), invite
    codes regenerated. Full fidelity **incl. secrets** (password/flag hashes, SMTP)
    — the file is sensitive; both endpoints gated on `manage_site_settings`.
    Excluded: `refresh_sessions` + the transient `notifications`/`collab_documents`/
    `dashboard_layouts`. `POST /site-settings/export` (file download) +
    `POST /site-settings/import` (returns per-table created/skipped) +
    `GET /site-settings/backup/sections`. New non-triggerable **`platform.imported`**
    event (`platform.*` excluded from automation triggers alongside `automation.*`).
    Frontend: `BackupPanel` (export section checkboxes → JSON download; import file
    picker → section checkboxes → additive result summary), `use-site-settings`
    hooks.
  - **Multiple-choice challenges + competition-wide guess cap** (§13.2) — a third
    `flag_type` (`multiple_choice`) alongside static/regex. The author supplies an
    option list + marks one correct; `challenges.choices` (JSON, public) holds the
    options and the **correct one is hashed in `flag_hash` like a static flag**, so
    the answer never leaves the server — the competitor submits the option they
    picked and it grades server-side unchanged. `ChallengeOut` exposes `choices` +
    `attempts_remaining` (per subject). Because a finite option set is trivially
    brute-forced, a **competition-wide** `Competition.mc_guess_limit` (**defaults to
    2**, applied at the API layer not as a column default so an explicit null =
    unlimited isn't clobbered; set in **competition settings**, *not* per-challenge —
    owner call) caps guesses per subject per MC challenge; `submit_flag` refuses further
    guesses **before grading** once the cap is hit (`subject_attempt_count[s]` in
    `utils/scoring`), returning `attempts_remaining`. Migration `d6e7f8a9b0c1`
    (adds both columns). Clone + the generic backup carry them. Frontend: the
    challenge editor gains an options editor (radio = correct), the challenge
    dialog renders radios + "N guesses remaining" + a locked state, and the
    competition settings form gains the guess-limit input. Reuses
    `challenge.created/updated` + `challenge.solved`; no new event. **Competition
    Settings is tabbed** (General / Schedule / Scoring / Modules) via a new
    dependency-free `Tabs` primitive; the settings form stays mounted across the
    non-module tabs (hidden, not unmounted) so switching never drops an unsaved edit.
  - **Multiple-choice guess resets** — staff can hand back guesses non-destructively
    (a misclick-locked competitor shouldn't be stuck). `mc_guess_resets` (new model
    + migration `e7f8a9b0c1d2`) records a **cutoff** (`created_at`); the guess count
    only tallies submissions *after* the latest applicable reset — targeted at a
    subject (`user_id`/`team_id`) or challenge-wide (both null = bulk). `subject_attempt_count[s]`
    apply the cutoff; submission history is untouched. `POST .../challenges/{id}/reset-guesses`
    (`challenge_edit`, MC-only) with `{user_id?|team_id?}` (empty = everyone), emits
    new §3.2 **`challenge.guesses_reset`** (a `challenge_edit`-governed trigger).
    Carried by the generic backup. Frontend: `ChallengeGuessesSection` in the MC
    challenge editor (team/competitor picker + "Reset for selected" / "Reset for
    everyone"), `useResetGuesses`.
  - **Challenge ratings** (§4.4 feedback extension) — solving a challenge prompts a
    competitor for a **1–5 rating** so staff/challenge-devs see which challenges
    landed well. Per-competition toggle `Competition.challenge_ratings_enabled`
    (default off, in competition settings → Scoring) + migration `f8a9b0c1d2e3`;
    `ChallengeRating` model (one per user per challenge, re-rating updates).
    Owner call: an **extension of the feedback module** — routes
    (`routers/challenge_ratings.py`, mounted by the feedback plugin) honour the
    feedback module's per-competition toggle *and* the ratings flag. `POST
    .../challenge-ratings/{chid}` (`feedback_submit`; must have **solved** it) +
    `GET .../challenge-ratings` (`feedback_view_responses`; per-challenge avg+count).
    `ChallengeOut.my_rating` drives the prompt (shows only when unrated). New §3.2
    **`challenge.rated`** (a `feedback_view_responses`-governed trigger). Backup
    carries the table; clone carries the flag. Frontend: `ChallengeRatingPrompt`
    (post-solve stars in the challenge dialog, gated on the flag + feedback module
    enabled), the settings toggle, and a **Challenge ratings** table on the Feedback
    page (`ChallengeRatingsPanel`); `useSubmitRating`/`useChallengeRatings`. Ratings
    also surface on the **analytics** challenges table (avg + count columns, added to
    `utils/analytics.challenge_analytics` + `ChallengeAnalytics`).
  - **Reusable confirmation dialog + platform-wide wiring** — a `ConfirmProvider` +
    imperative **`useConfirm()`** (`components/ui/confirm.tsx`, mounted in
    `providers`): `if (!(await confirm({title, description?, confirmLabel?,
    destructive?}))) return;` before a consequential action, one consistent modal, no
    per-site boilerplate. Wired into every destructive/consequential action: delete
    challenge / category / attachment / hint / role / automation rule / survey /
    survey-question / competition (kept its bespoke dialog) / user; ban user;
    unassign role; archive competition; unpublish challenge; reset guesses for
    everyone; leave team; import backup. The two existing bespoke confirm dialogs
    (user delete) migrated to `useConfirm`; restorative actions (unban, unarchive,
    publish, targeted guess reset) and personal-pref/creative ones (dashboard reset,
    clone, module toggle) intentionally skip it.
  - **Competition Settings "Scoring" tab → "Challenges"** (owner rename; better fits
    future settings).
  - **Event rename `feedback.submitted` → `survey.submitted`** (§3.2): the
    survey-submission event now sits in the `survey.*` namespace beside the
    existing `survey.opened`, rather than the odd `feedback.*` outlier (challenge
    ratings keep their own separate `challenge.rated`). Catalog-driven, so the
    rule builder's trigger list updates automatically; touched the event +
    automation catalogs, the `feedback` router emit, tests, and docs. No
    migration — pre-release, no stored automation rules to remap.
  - **Awards carry points + manual judge awards** (§5.3): the automation action
    `award_achievement` → **`create_award`** (label "Create award") and its
    backing `Achievement` gained a **`points`** column that now **folds into the
    scoreboard** (`utils/scoreboard._award_points_by_subject`, alongside
    `ScoreAdjustment`) — an award is a title + description + point value, not a
    badge-only record (0 points = pure badge). The action's config gained
    `points` and its `name` field became `title`; the `achievement.awarded`
    payload carries `title`/`points`. **Manual awards**: judges (`score_override`)
    grant awards from the individual-mode participants roster — `POST
    /api/competitions/{id}/awards` (`routers/awards.py`, mounted by the
    `competitions` plugin) takes `{user_ids[], title, description?, points}`,
    validates each recipient is a competition Participant (§7.5), records
    `awarded_by_user_id` provenance, and emits `achievement.awarded` per grant
    (so audit + automation rules watching awards behave identically to
    engine-granted ones). Migration `a9b0c1d2e3f4` (rename `name`→`title`, add
    `points` + `awarded_by_user_id`); backup remaps the new FK; catalog-driven so
    the rule builder shows the new action/fields automatically. Frontend:
    `ParticipantsPanel` "Create award" button + `AwardDialog` (multi-select
    recipients, title/description/points), `useCreateAward` (invalidates roster +
    scoreboard). Clone still skips awards (score-state, clean slate).
  - **Per-user notification preferences** (§4.4) — the `/profile` preferences
    section (was a placeholder) is now functional. `User.notification_prefs`
    (JSON, nullable = all-default; migration `b0c1d2e3f4a5`) holds four booleans:
    **in-app category mutes** `inapp_tickets` / `inapp_automations` (gate whether
    a bell notification is *created* — honored centrally in
    `utils/notifications.create_notifications`, so every producer — ticket
    listeners + the automation `notify` action — respects them; category derived
    from the notification `type`, `ticket.*` vs. everything-else) and two
    **client-honored delivery hints** `browser` / `sound`. `GET/PUT
    /api/notifications/preferences` (own-user, no catalog perm). Owner call: **no
    per-user email** (email stays automation-rule-driven; would need a
    backgrounded send + SMTP). Frontend: `lib/notification-prefs.ts` (a
    module-level delivery-hint cache read by the ticket audio cue + the WS
    browser-notification path, kept warm by `useNotificationPreferences` mounted
    in the app shell), `useUpdateNotificationPreferences`, `NotificationPreferencesCard`
    on `/profile` (browser toggle requests the OS `Notification` permission on
    enable). Backup carries the column (plain JSON on `users`, no FK).
  - **Pre-ship feature-parity tranche** (owner ask — CTF-platform table-stakes
    other platforms ship; built in order, each its own commit):
    - **Dynamic (decay) scoring** (§13.2) — a per-challenge `scoring_type`
      (`static` default | `dynamic`) + `min_points`/`decay` (migration
      `c1d2e3f4a5b6`). Dynamic uses the CTFd quadratic model: worth `points`
      initially, decaying toward `min_points` over `decay` solves. `utils/scoring`
      gains `dynamic_value`/`challenge_value`; the submit path recomputes the
      award and **re-values all prior solvers' `points_awarded`** on each new
      solve so everyone converges to the current value (scoreboard read path —
      `sum(points_awarded)` — unchanged). `ChallengeOut` gains `scoring_type`/
      `min_points`/`decay` + a computed **`value`** (current worth; cards show
      this, `points` stays the configured initial). Validated (dynamic needs
      min+decay, min ≤ points). Clone + backup carry the columns. Frontend:
      challenge editor scoring selector + min/decay fields, cards/dialog show
      `value` with a "dynamic" marker.
    - **Scoreboard freeze** (§13) — `Competition.scoreboard_frozen_at` (migration
      `d2e3f4a5b6c7`). `compute_scoreboard` gained an as-of path (`live=` /
      `freeze_cutoff`): frozen → the board is computed as of the freeze instant
      (dynamic values by solve count then; later solves/adjustments/awards/hints
      excluded) for everyone; the WS room serves the frozen snapshot. Staff read
      live with `?live=true`. `POST .../scoreboard/freeze`(+`/unfreeze`) gated on
      `scoreboard_freeze`, emitting new §3.2 `scoreboard.frozen`/`unfrozen`
      (triggers, governed by `scoreboard_freeze`). Refactor removed the SQL
      `_awarded_totals` subquery for a unified per-subject awarded dict; also
      subscribed the scoreboard broadcast to `achievement.awarded` (manual awards
      now move the board live). `ScoreboardOut` gains `frozen`/`frozen_at`.
      Frontend: `useFreezeScoreboard`, a "Frozen" badge + staff Freeze/Unfreeze
      button on the scoreboard page.
    - **Solver list + first-blood display** — `GET .../challenges/{id}/solves`
      (`challenge_view`, `ChallengeSolver` schema): who solved a challenge,
      earliest-first, the first tagged `is_first_blood`. Read-only off
      submissions (no migration/event). Frontend: `useChallengeSolves` +
      a "Solves (N)" section in the challenge dialog with a 🩸 first-blood marker;
      auto-refreshes on solve (shares the `["challenges", comp]` invalidation).
    - **Public / spectator scoreboard** — the one **unauthenticated** read:
      `GET /api/public/competitions/{id}/scoreboard` (`routers/public_scoreboard.py`,
      mounted by the scoring plugin) serves a `public`, non-archived competition's
      board (`PublicScoreboardOut` = board + name/start/end); anything else 404s so
      private competitions aren't disclosed. Respects the freeze (spectator =
      non-staff). Frontend: a standalone `/public/[competitionId]` route **outside
      the (app) shell** (no auth), `usePublicScoreboard` (30s poll, no auth gate),
      branded via public site settings + the mandatory Powered-by footer.
    - **CTFtime scoreboard feed** — `GET /api/public/competitions/{id}/ctftime`
      (same public router/gating) returns the [CTFtime format](https://ctftime.org/json-scoreboard-feed)
      `{"standings":[{"pos","team","score"}]}` so a public event can be rated.
      Staff see the public-board + CTFtime-feed URLs on the scoreboard page when
      the competition is public.
    - **Scheduled / waved challenge release** — `Challenge.release_at` (migration
      `e3f4a5b6c7d8`). A published challenge with a future `release_at` stays
      hidden from competitors (list filter + `load_visible_challenge` 404 via a
      shared `_is_released`); staff always see it. `ChallengeCreate/Update/Out`
      carry `release_at`. Clone clears it (schedule = clean slate); backup carries
      it. Frontend: a `datetime-local` "Release at" field in the editor + a
      "· scheduled" marker on the admin row. **Also fixed a latent test-infra
      gap**: `models/__init__` didn't import `MCGuessReset`/`ChallengeRating`, so
      their tables were only registered by import side-effects (the participant
      challenge-list path — which always queries `mc_guess_resets` — 404'd "no
      such table" in isolation); both are now imported so `Base.metadata` is
      complete.
    - **Challenge prerequisites / unlock chains** — `Challenge.prerequisites`
      (JSON challenge-id list; migration `f4a5b6c7d8e9`). **Shown-locked**: a
      competitor sees a challenge with an unsolved prerequisite but can't
      open/submit it. `ChallengeOut` gains `prerequisites` + a per-subject
      `locked` (staff/subjectless always unlocked; `_is_locked` off the subject's
      solved set). Enforced server-side in `submit_flag` (403 while locked);
      validated on create/update (prereqs must be same-competition challenges, no
      self-reference). Clone **remaps** prereq ids to the new challenges (2nd
      pass); backup carries the JSON (ids not remapped — a known limit shared with
      automation-config ids). Frontend: a prerequisite checkbox picker in the
      editor, a "🔒 Locked" card badge, and a locked dialog panel naming the
      unsolved prerequisites by title.
    - **Tags & difficulty (per-competition managed vocab)** — `Competition`
      gains `challenge_tags` + ordered `difficulty_tiers` (managed lists);
      `Challenge` gains `tags` + `difficulty` (migration `a5b6c7d8e9fa`), both
      **validated against the competition's vocab** on create/update (off-vocab →
      400). `ChallengeOut` exposes `tags`/`difficulty`; `CompetitionOut` exposes
      the vocab. Clone carries the vocab + per-challenge metadata; backup carries
      the columns. Frontend: `VocabEditor` (add/remove chips) on Competition
      Settings → Challenges; a tag-chip + difficulty-select picker in the
      challenge editor (only shown once vocab exists); difficulty badge + tag
      chips on the browse cards.
    - **Bulk challenge import/export (ctfcli YAML, zipped)** — `utils/challenge_yaml.py`:
      `GET .../challenges/export` (`challenge_edit`) zips one `<slug>/challenge.yml`
      per challenge (ctfcli format) + attachment files; `POST .../challenges/import`
      (`challenge_create`, 50 MB cap) bulk-creates from such a zip, **additive**
      (skip by existing title). Field map: name/category(created)/description
      (TipTap↔plain)/value/`type:dynamic`+`extra`/flags(static+regex)/tags(unioned
      into vocab)/`extra.difficulty`/hints/files/state/prerequisites(by **title**,
      resolved post-pass). **Static flags omitted on export** (stored hashed; regex
      round-trips) — import hashes the plaintext the YAML supplies, so
      authoring→import is lossless. Routes registered **before** `/{challenge_id}`
      so `/export` isn't captured as an id. Like the platform backup import, bulk
      import emits no per-row event (atomic authoring op). Frontend: Export/Import
      buttons on the Manage-challenges header (`useExportChallenges`/`useImportChallenges`,
      reusing the `downloadFile` helper).
    - **Pre-Group-C adjustments** (owner batch, migration `b6c7d8e9fab0` adds
      four `Competition` cols):
      - **Public scoreboard is now an explicit per-competition opt-in**
        (`public_scoreboard`, default off) decoupled from `visibility`; the
        spectator board gate + the new `GET /api/public/competitions` **directory**
        use it. Frontend: a **`/public` landing page** (lists opted-in
        competitions → `/public/[id]`), toggle on **Settings → General**.
      - **CTFtime feed is a separate per-competition opt-in** (`ctftime_enabled`,
        default off); the feed URL is shown on Settings → General when enabled and
        **removed from the scoreboard page**.
      - **First-blood marker** changed from the 🩸 emoji to an inline
        lightning-bolt SVG (`FirstBloodIcon`, warning-coloured), matching the app's
        icon idiom.
      - **Scoreboard-freeze semantics clarified**: a `useConfirm` on Freeze
        explains competitors keep solving + points still count (the board just
        stops moving publicly), plus a persistent frozen note on the board.
      - **New automation actions** `freeze_scoreboard` / `unfreeze_scoreboard`
        (set `scoreboard_frozen_at`, emit `scoreboard.frozen`/`unfrozen`) +
        `create_announcement` (posts an announcement, emits `announcement.published`).
        **New lifecycle triggers wired**: `competition.started` / `competition.ended`
        (already in the catalogs but dead) now **emitted by the scheduler**
        (`emit_lifecycle_events`, dedup via `started_event_fired`/`ended_event_fired`)
        when start_at/end_at is crossed — enables "on end → freeze + open survey".
      - **Challenges page**: an availability filter (**All / Available / Locked**),
        shown only when prerequisites lock something.
      - **Categories moved to Settings → Challenges** (alongside the tag/difficulty
        vocab, for uniformity); `CategoryManager` exported + removed from the
        Manage-challenges area.
    - **Brackets / divisions** (Group C) — parallel rankings a competitor
      **self-selects**. `Competition.brackets` (JSON vocab, Settings → General) +
      a subject-keyed `bracket_memberships` table (`subject_id` = team id
      team-mode / user id individual-mode — the §13.2 scoring subject, so one
      table serves both modes; migration `c7d8e9fab0c1`). `PUT/GET
      .../bracket` (self, via `resolve_subject`) + `PUT .../bracket/{subject_id}`
      (staff `team_view_all` override); validated against the vocab
      (`utils/brackets`). `compute_scoreboard` labels each entry with its
      `bracket`, carries the vocab, and takes a `bracket=` filter (ranks within
      the division). `ScoreboardOut` gains `bracket` per entry + `brackets`.
      Frontend: `VocabEditor` on Settings → General, a Division **filter**
      (client-side off the labeled board, so it stays live over WS) + a "Your
      division" **picker** on the scoreboard (`use-brackets`). Clone carries the
      vocab; `bracket_memberships` excluded from backup (per-subject state, like
      scores' finer bits — polymorphic subject_id can't be cleanly remapped).
    - **Team quality-of-life** (Group C) — three team-mode niceties:
      - **Max team size** (`Competition.max_team_size`, null = unlimited) enforced
        at join + on request-approval (409 when full); Settings → General (team
        mode).
      - **Team profile** (`Team.affiliation`/`country`/`website`) — captain-editable
        via `PATCH .../teams/me` (name-clash guarded); shown on the team panel.
      - **Invite-code + optional approval** (`Team.approval_required` + a
        `team_join_requests` applications table / `TeamApplication` model). Joining
        an approval-required team files a **pending request** (`join` now returns
        `TeamJoinResult {pending, team}`); the captain lists
        (`GET .../teams/me/requests`) and **approves** (→ membership, size-checked,
        emits `team.member_joined`) or **rejects**. Migrations `d8e9fab0c1d2`
        (size+profile) + `e9fab0c1d2e3` (approval). Frontend: create-form + profile
        approval toggle, a pending-request join toast, and a captain "Join
        requests" section with Approve/Reject (`use-teams`).
    - **Self-service password reset** (Group D, ADR-0003) — a `password_reset_tokens`
      table (`PasswordResetToken`; only the SHA-256 is stored, like refresh
      sessions; migration `fab0c1d2e3f4`). `POST /api/auth/forgot-password` {email}
      always **204** (never discloses whether an account exists), mints a 1-hour
      token and emails `{cors_origin[0]}/reset-password?token=…` via the existing
      `mailer` (no-ops if SMTP unconfigured). `POST /api/auth/reset-password`
      {token, new_password} validates the unexpired token, sets the password,
      deletes the token(s) + revokes every refresh session, emits
      `user.password_changed`. Frontend: a "Forgot password?" link on login →
      standalone `/forgot-password` (request) + `/reset-password` (set) pages
      (`useForgotPassword`/`useResetPassword`), both outside the app shell.
    - **Pause competition + brackets are staff-assigned** (owner follow-ups):
      - **Pause** (`Competition.paused`, migration `0b1c2d3e4f5a`) — a General-tab
        toggle that halts gameplay: `submit_flag` 403s for competitors while paused
        (staff with `challenge_edit` bypass, to test). Distinct from a scoreboard
        freeze (which only stops the board updating). No new event (set via the
        existing competition `PATCH` → `competition.updated`). Frontend: a paused
        banner on the challenges page + a paused note replacing the submit form.
      - **Brackets are now staff-assigned, not self-select** — removed the
        competitor `GET/PUT .../bracket` self endpoints; `PUT .../bracket/{subject_id}`
        is regated `team_view_all` → **`edit_competition`** (admin/judge,
        competition-scoped). Frontend: dropped the "Your division" competitor picker
        for an **inline per-row division `<select>`** on the scoreboard (staff only,
        `useSetSubjectBracket`); the Division filter stays for everyone.
  - **Test-suite hardening**: `conftest` drains `event_bus.wait_for_background()`
    before `drop_all` so fire-and-forget automation tasks (ADR-0012) can't leak
    across the per-test schema and flake unrelated tests.

Read before touching the relevant area: ADR-0008 (stateful refresh
sessions), ADR-0012 (event-dispatch sync-critical vs background, supersedes
ADR-0009), ADR-0013 (webhook egress hardening), ADR-0014 (CRDT transport —
dumb relay + client snapshot), ADR-0011 (site-wide theming only —
per-competition deferred), ADR-0015 (username-primary identity, optional
email), ADR-0016 (export/import backup), ADR-0017 (first-run setup wizard,
supersedes the seeded admin of ADR-0010).
There is **no seeded default admin** in production: a fresh install ships with
**no** administrator and is *unconfigured* until an operator completes the
**first-run setup wizard** (`/setup`, ADR-0017), which creates the owner account
(no hard-coded creds) + initial branding. `auth.setup.instance_needs_setup`
(no active Administrator ⇒ true) gates the wizard and blocks public registration
until an owner exists; the frontend `SetupGuard` redirects to `/setup` while
unconfigured. Public registration never grants above Participant. **The test
suite still seeds `admin@example.com` / `changeme` in its fixtures** (conftest),
so `admin_token` and existing tests are unaffected.

**Tier 2 scope notes** (owner decisions, reflected in the plan): the
challenge lifecycle (ROADMAP #17) is **deferred to a future tier**, and
theming is **site-wide only** for now (ROADMAP #20 rescoped from
per-competition; ADR-0011).

**Local dev note:** `.claude/launch.json`'s backend config runs against
SQLite by default (`DATABASE_URL` env var overrides it) so `preview` needs
no infra, matching the test stack (ADR-0006). Migrations run automatically
on every start. `docker compose up` is now the **production** stack (Caddy
single-origin on :8080); for the full Postgres/Redis/MinIO **dev** stack with
hot reload use `docker compose -f docker-compose.dev.yml up`.

**Migrations aren't covered by the test suite** (it builds the schema from
`Base.metadata`, not by running migrations — ADR-0006), and SQLite silently
accepts things Postgres rejects (e.g. `SET boolcol = 1` — Postgres needs
`TRUE`). So a migration bug only surfaces against real Postgres: run `docker
compose up` (or the dev stack) at least once before shipping a migration.

## Non-negotiable architectural rules

From `docs/ARCHITECTURE.md` §1, enforced by convention and code review
(and, where marked below, by ESLint — `frontend/eslint.config.mjs`) — treat
these as hard rules, not defaults to reconsider per-feature:

- **Every mutation emits an event** through the event bus (§3), using the
  `<entity>.<verb>` past-tense vocabulary already defined in §3.2. Don't
  invent a new event type without adding it there first.
- **Every query and route is scoped by `competition_id`** at the
  data-access layer, never left to an individual endpoint to remember
  (§6.2). Writing a query against a tenant-scoped table with no
  `competition_id` filter is a bug, not a shortcut.
- **Permission checks go through `require_permission`**, never an inline
  role check (§7.6). If the permission you need doesn't exist yet, add it
  to the categorized list in §7.1 first.
- **One hook module per frontend domain** under `frontend/src/lib/hooks/`
  (§8). Components never call the API client directly. *(ESLint: no
  `@/lib/api` import outside `lib/hooks/`.)*
- **Colors and spacing come from design tokens**, never a raw hex value
  or magic number in a component (§9). Missing a token is a reason to add
  the token, not to inline the hex. *(ESLint: no raw hex literals in
  `app/`/`components/`, brand mark excepted.)*
- **New backend features register through the module loader** (§11.1),
  including required-core ones — check §11.3 for which tier a feature
  belongs to before deciding whether it needs an admin-facing toggle.

## Don't build yet

Explicitly deferred past MVP (`docs/ROADMAP.md`, "Explicitly Deferred"
section). If a task seems to need one of these, flag it and ask rather
than quietly building a scoped-down version:

- AI integration — administrator or competitor assistant.
- SSO / LDAP / SAML — password auth only until after public launch
  (`docs/adr/0003-jwt-access-refresh-auth.md`).
- Plugin marketplace / third-party modules — the module *mechanism* is
  used for required-core features starting in Tier 0, but the
  marketplace path (listing/discovery + untrusted-code sandboxing) stays
  closed.
- Multi-competition tenancy *consolidation views* — `competition_id`
  scoping is required from Tier 0; cross-site rollups are not.
- Per-competition / white-label theming — site-wide only for now
  (ADR-0011); the per-competition variant may return later.

Note: the **automation engine**, **dashboard drag-and-drop**, and
**collaborative rich-text/CRDT editing** were on this list but an owner
revision moved them into **Tier 3** (see `phase_3.md`). Build them in
phase order, not ad hoc — the plan is what to follow.

## Stack

Fixed by `docs/ARCHITECTURE.md` §2 — don't substitute an alternative to
something already decided there (e.g. Zustand + TanStack Query, not
Redux; SQLAlchemy 2.x async, not a different ORM).

```
# Whole PRODUCTION stack (Caddy + backend + frontend + Postgres/Redis/MinIO).
# Caddy fronts everything single-origin; the backend runs `alembic upgrade head`
# before serving, so the DB is migrated + roles seeded on first boot.
docker compose up --build            # app on http://localhost:8080
# DEV stack (hot reload, source-mounted, dev servers):
docker compose -f docker-compose.dev.yml up --build   # frontend :3000, backend :8000

# Backend only (needs a venv — this host's Python is externally-managed)
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/alembic upgrade head          # against a reachable Postgres
.venv/bin/uvicorn main:app --reload

# Frontend only — REQUIRES Node 20+ (Tailwind v4's engine, @tailwindcss/oxide).
cd frontend && npm install && npm run dev
```

<!-- Verified end-to-end on 2026-07-18: docker compose up migrates + seeds,
register->admin bootstrap, RBAC-gated competition create (participant 403),
and competition.created/user.registered land in audit_log. Local Node here
is 18, which can't run the frontend (Tailwind v4 needs Node 20); the Docker
frontend image is node:20-alpine, so `docker compose up` is the reliable
path on this machine. -->

## Code conventions

- Backend: Pydantic schemas (`backend/schemas/`) are separate from
  SQLAlchemy models (`backend/models/`) — never return a model directly
  from a route.
- Backend: one FastAPI router per domain (`backend/routers/`), mirroring
  the one-hook-per-domain convention on the frontend.
- Frontend: server state through TanStack Query hooks only; Zustand is
  for client/UI state (auth, active competition, prefs) — don't put
  server data in a Zustand store.
- Migrations: `YYYY-MM-DD_<revid>_<desc>.py`, one migration per PR. Never
  hand-edit a migration that's already been applied anywhere.

## Testing

Established in Tier 0 (see `docs/adr/0006-testing-stack.md`):

- **Backend:** pytest + pytest-asyncio, httpx ASGI transport, SQLite
  (aiosqlite) so no infra is needed. `cd backend && .venv/bin/pytest`.
  The suite builds the schema from `Base.metadata` and seeds roles from
  `auth/seed.py` (the same specs the migration uses).
- **Frontend:** Vitest + Testing Library + jsdom.
  `cd frontend && npm run test`.

Keep SQLite/Postgres differences in mind (models stay portable, generic
`JSON`, `render_as_batch` migrations) — the ADR spells out the tradeoff.

## Keeping this file honest

If you catch yourself re-explaining the same thing twice in a session, or
a rule here turns out to be wrong, fix it here. If it's a real
architectural decision (not just a typo), update `docs/ARCHITECTURE.md`
and/or add an ADR too — don't let this file and the real docs drift apart.