# Roadmap

Flagpost shipped **v1.0.0 on 2026-07-25**; the latest tag is **v1.5.0**
(2026-08-24). `main` is now `1.5.0-src`, accumulating the **v1.6.0** milestone.
This document has two halves:

- **[Tiers 0–3](#tier-0--foundation)** — the pre-1.0 build order, breaking
  `ARCHITECTURE.md` and `VISION.md` down into the feature list that got the
  platform to a public release. All four tiers are complete; this half is now a
  **historical record** of what was built and in what order, kept because the
  reasoning in it still explains why the codebase is shaped the way it is.
- **[Post-1.0 releases](#post-10--release-milestones)** — the live plan. Work is
  tracked as GitHub issues against **version milestones**, not tiers.

**Where to look for what's next:** the
[milestones page](https://github.com/tbcsec/flagpost/milestones) is the source of
truth. The summary here is a convenience and can lag it.

## How to read the tiers

Tiers are ordered by importance: **Tier 0 is scaffolding nothing else can
be built without; Tier 1 is what makes the platform minimally usable to run
a real competition; Tier 2 is what makes it good enough that organisers
prefer it to what they're using now; Tier 3 is polish worth doing before a
public launch, but not before Tier 1/2.** Within each tier, items are
listed in the order they should be built — later items in a tier often
depend on earlier ones.

The original MVP scope deliberately excluded the automation engine, AI
assistance, external identity providers, the plugin marketplace, and multi-site
tenancy — none of them were required for an organiser to run a competition
better than a spreadsheet + Discord. Three of those exclusions have since
lifted: the **automation engine** (with dashboard drag-and-drop and CRDT
editing) was pulled into Tier 3, **external identity providers shipped** (OIDC
in v1.2.0, then SAML and LDAP in v1.3.0), and the **AI assistants shipped in
v1.4.0**. What's still deferred is listed at the bottom.

---

## Tier 0 — Foundation

**Status: ✅ complete (tagged `tier-0`).**

Nothing user-facing yet. Get this wrong and everything built on top of it
gets expensive to fix later; get it right and every later tier is faster
to build, not slower.

1. **Auth & RBAC** — registration, login, session handling (local
   password auth per Architecture §7.7; OIDC arrived later in v1.2.0,
   see Explicitly Deferred below), and the role and permission model from
   Architecture §7: the three built-in roles (Administrator, Judge,
   Participant), per-competition role assignment, and the categorized
   permission list, even if the custom-role editor UI (§7.4) waits until
   Tier 2. Team membership can come later, but the permission system it
   plugs into needs to exist first.
2. **Competition entity & scoping** — the `competition_id` model from
   Architecture §6, even though multi-site consolidation views are
   explicitly out of scope for MVP. Every other entity (challenges, teams,
   tickets) hangs off this from day one; retrofitting scoping onto tables
   that didn't have it is far more expensive than building it in from the
   start.
3. **Design system / token layer** — the CSS custom property + Tailwind
   `@theme` setup from Architecture §8, and a first pass at the core
   shadcn/ui-style component primitives (button, input, card, dialog,
   table). This is what makes every subsequent feature look finished
   instead of like a form dump, and it's much cheaper to establish before
   thirty screens exist than to retrofit after.
4. **Event bus, minimal** — the pub/sub mechanism from Architecture §3,
   wired into the handful of mutations Tier 1 needs (challenge solved, user
   registered, etc.) and consumed by nothing but the audit log for now.
   Build the *mechanism*, not the automation engine that consumes it later
   — emitting events costs almost nothing at write time and is expensive
   to backfill once mutations exist without it.
5. **Domain hook / query layer conventions** — establish the
   one-hook-per-domain pattern (Architecture §8) with the first one or two
   domains (competitions, users), so every feature after this follows the
   same pattern instead of the first few features setting a bad precedent.

---

## Tier 1 — Minimum Viable Competition

**Status: ✅ complete.** All of items 6–15 are built and wired end to end,
plus a batch of pre-Tier-2 fixes/enhancements (competition join for
individual-mode play, enforced visibility, role-aware navigation, an admin
audit-log/event viewer, and UI polish). See `.claude/CLAUDE.md` → "Current
build stage" for the full list.

This is the actual MVP: enough to run one competition, live, end to end.

6. **Competition management (admin)** — create/edit a competition, set
   name, description, start/end time, registration open/close, visibility
   (public/private).
7. **Team management** — create a team, invite/join a team, leave a team,
   solo-vs-team mode toggle per competition (some CTFs are solo-only).
   *(The individual-mode counterpart — a `/participants` competitor roster with
   standing — was wired in the ad-hoc Tier 3 Phase 9.)*
8. **Challenge CRUD (admin)** — title, description (rich text), category,
   points, flag (with basic flag formats — static, regex, case-insensitive
   toggle), file attachments, visibility toggle. No review workflow yet
   (see Tier 2) — a challenge is either draft or published.
9. **Challenge categories** — simple tagging/grouping (web, pwn, crypto,
   forensics, etc.), used for navigation and later analytics.
10. **File/asset storage** — MinIO-backed upload and serving for challenge
    files, sized and typed appropriately; this is a dependency for #8, not
    optional.
11. **Challenge browsing & submission (competitor)** — the competitor-facing
    challenge list, detail view, and flag submission form. This is the
    single screen competitors will spend the most time on — worth the
    design-system investment from Tier 0 paying off here first.
12. **Scoring** — point awarding on correct submission, duplicate-submission
    handling, basic scoring rules (static points to start; dynamic/decay
    scoring can follow later without changing the data model).
13. **Live scoreboard** — real-time (via the WebSocket layer, Architecture
    §4.1) team/individual rankings. This is the feature most likely to be
    compared directly against whatever the organiser is replacing, so it
    should feel obviously better, not just adequate.
14. **Announcements** — admin posts a message, all competitors see it,
    ideally pushed live rather than requiring a refresh (same WebSocket
    layer as the scoreboard).
15. **Basic hints** — a hint attached to a challenge, revealed on request,
    optionally at a point cost. Automation-*driven* release (unlocking a hint
    from a rule) is the `release_hint` action (Architecture §5.3) — since
    shipped in Tier 3 Phase 1; the Tier 1 reveal itself is the explicit,
    point-costed one.

At the end of Tier 1, someone can run a real competition on the platform,
live, with a scoreboard, and it will look and feel modern doing it. That's
the MVP line.

---

## Tier 2 — Makes It Good, Not Just Functional

**Status: complete** — built phase-by-phase per `docs/claude_plans/phase_2.md`.
Phase 0 (pre-Tier-2 gap fixes), Phase 1 (#16, judge/admin dashboard), Phase 2
(#18, support tickets), Phase 3 (#19, presence), Phase 4 (#20, site-wide
theming) and Phase 5 (#21, custom role editor) all shipped. Two owner scope
changes from the list below carried through: **item 17 (challenge
lifecycle) is deferred** (needs more design — still unscheduled, with no
milestone), and **item 20 is rescoped from per-competition to site-wide
theming** (the
per-competition/white-label variant may return later if demand warrants —
see ADR-0011).

What turns "we could technically use this" into "we'd rather use this than
what we have."

16. **Judge/admin dashboard** — the operational overview from `VISION.md`
    (active competitors, recent solves, challenge health at a glance).
    Ship with a **fixed layout** — the drag-and-drop customization in
    Architecture §10 is real, but it's a layer on top of a dashboard that
    already exists, not a prerequisite for having one.
17. **Challenge lifecycle (lightweight)** — add Draft → Review → Published
    states and an author field to challenges. This is a trimmed version of
    the full lifecycle in `VISION.md` (no testing sign-off workflow, no
    version history yet) — enough that a team of organisers isn't
    stepping on each other publishing half-finished challenges.
    **Deferred** (owner decision) — wants more design first. Still
    unbuilt and unscheduled as of v1.4.0.
18. **Basic support tickets** — a competitor can ask a question tied to a
    challenge; a judge can respond and mark it resolved. No routing rules,
    no analytics on response time yet — just replacing the "ask in
    Discord" pattern with something that has a record.
19. **Presence indicators** — "N people viewing this challenge" / "a judge
    is looking at this ticket" using the presence layer from Architecture
    §4.1. Cheap to add once the WebSocket infrastructure exists for the
    scoreboard, and it's the detail that makes the platform feel alive
    rather than just functional.
20. **Site-wide theming** — palette/accent selection from Architecture §9,
    applied **globally / site-wide** (an administrator sets one platform
    theme for the whole install), wiring the Admin → Appearance surface.
    *(Rescoped from the original "per-competition theming" — themes are
    site-wide only for now; the per-competition/white-label variant is
    deferred and may return later if demand warrants. See ADR-0011.)*
21. **Custom role editor (admin)** — the clone-and-edit UI for roles from
    Architecture §7.4: clone Judge/Participant (or start blank), toggle
    permissions from the categorized list. The three built-in roles from
    §7.3 already cover Tier 1 by themselves; this is what lets an
    organiser hand out narrower access (e.g. a challenge-author-only role)
    once they need to.

---

## Tier 3 — Pre-Launch Polish

**Status: ✅ complete** — built phase-by-phase per `docs/claude_plans/phase_3.md`
(automation-first, full spec). Phases 0–8: Phase 0 (notification-center +
event-dispatch groundwork, ADR-0012); the **full automation engine (#25)**
across Phases 1–3 — the engine + all eight §5.3 actions + the first optional
per-competition-toggleable module (Phase 1), webhook hardening (Phase 2,
ADR-0013), and the §5.5 visual rule builder (Phase 3); **feedback/survey (#22)**
(Phase 4, the second optional module + automation glue); **challenge & team
analytics (#23)** (Phase 5, the third optional module); **dashboard
drag-and-drop (#26)** (Phase 6, per-user layout customization on the Tier-2
widget registry); **collaborative rich-text / CRDT editing (#27)** (Phase 7,
Y.js team scratchpad + staff ticket notes, ADR-0014); and **onboarding / empty
states (#24)** (Phase 8, guided first-run states + a manager getting-started
guide). The owner-inserted ad-hoc **Phase 9** (pre-release features & cleanup,
added 2026-07-23) then shipped its full tranche — multiple-choice + dynamic
(decay) scoring, scoreboard freeze + public/spectator + CTFtime feeds,
brackets/divisions, team QoL + captain approval, scheduled release +
prerequisites, tags/difficulty vocab, bulk ctfcli-YAML import/export,
self-service password reset, point-bearing awards, and more (see
`.claude/CLAUDE.md` → "Current build stage" for the itemised list). **Phase 10
(#28)** — the accessibility / responsiveness / optimization pass — shipped as a
four-stage pre-public pass (accessibility, full bug pass, optimization + motion,
in-depth security review). Release engineering on top: the AGPL-3.0 license, a
single-origin production Docker stack, a marketing README, and demo mode + the
hosted demo (demo.flagpost.io). All of this shipped as **v1.0.0** on
2026-07-25 — see [Post-1.0 releases](#post-10--release-milestones) for what
came after.

Worth doing before a public/1.0 release, not worth doing before Tiers 1–2
are solid.

22. **Feedback/Survey** — post-competition survey (competition scoped) per `VISION.md`,
    with full editor. Include rating scale (1-10, 1-5), short text, long text, multiple choice.
    Ability to export competition survey responses in .csv format as well as a trigger.
23. **Challenge & Team analytics** — solve count, completion rate, average
    solve time per challenge. Read-only reporting off data that's already
    being captured by Tier 1 — no new instrumentation required, just
    surfacing it.
24. **Onboarding / empty states** — first-run experience for a brand-new
    competition with no challenges yet, empty scoreboard states, etc. Easy
    to skip, very noticeable when skipped. *(Shipped — Tier 3 Phase 8:
    reusable `EmptyState` + role-aware guided states across challenges /
    scoreboard / support / feedback, and a manager "Getting started"
    dashboard guide.)*
25. **Full automation engine** (Architecture §5) — conditions/actions UI,
    webhook actions and their hardening, personal automation rules. The
    event bus built in Tier 0 is what makes this addable later without a
    rewrite; it's just not worth building the rule engine and its security
    hardening before there's a stable set of events to automate against.
26. **Dashboard drag-and-drop customization** (Architecture §10) — ships as
    a fixed layout in Tier 2; the customizable layer is additive UI on top
    of a dashboard that already works, not a blocker for one. *(Shipped —
    Tier 3 Phase 6: per-user `dashboard_layouts` + edit mode with
    drag-reorder / size-cycle / show-hide / reset-to-default, gated on
    `customize_dashboard`.)*
27. **Collaborative rich-text editing** (Architecture §4.2) — both the
    staff and team-facing cases. Real-time *presence* (Tier 2, #19) ships
    first; true CRDT co-editing is a bigger lift, pulled into Tier 3 from
    the previously-deferred list. *(Shipped — Tier 3 Phase 7: Y.js under
    TipTap over the WS layer; team per-challenge scratchpad + staff ticket
    notes via the required-core `collab` module; dumb-relay transport +
    blob persistence, ADR-0014.)*
28. **Accessibility, Responsiveness, and Optimization pass** — keyboard navigation, contrast,
    mobile layout for the competitor-facing screens in particular (people
    check scoreboards from their phones), a full optimization pass. *(Shipped —
    Tier 3 Phase 10, run as a four-stage pre-public pass: an accessibility pass,
    a full bug pass, an optimization + motion-layer pass, and an in-depth
    security review & testing pass.)*

---

## Post-1.0 — release milestones

Everything above got the platform to **v1.0.0 (2026-07-25)**. From that point on
the unit of planning is a **version milestone** on GitHub, not a tier — each one
a small, shippable batch rather than a months-long phase.

> **Read `#N` in this section as a GitHub issue.** The numbered items in the
> tiers above are *roadmap item* numbers, a separate sequence that started
> before the repository was public — so roadmap item 23 (challenge analytics)
> and issue #23 (judge insight cards) are unrelated. Only this section's
> numbers are issues.

### Shipped

**v1.0.0** — the initial public release: Tiers 0–3 complete, plus the release
engineering on top (AGPL-3.0, the single-origin Caddy production stack, the
marketing README, and demo mode + the hosted demo at demo.flagpost.io).

**v1.1.0** — the first post-release batch, mostly "the platform should feel
live and legible":

- **Live updates everywhere** (#18) — a per-competition `activity` WebSocket
  room fans id-only pings from a curated event allowlist, so every page
  refreshes its own permission-filtered slice instead of going stale.
- **A reusable data-table layer** (#16 #17 #20) — headless sort / search /
  pagination rolled out across the table and card surfaces.
- **Spectator insights + points timeline** (#24) — the public board gained
  insight cards and a live cumulative-points chart, computed under the same
  freeze cutoff as the board itself.
- **Judge insight cards** (#23) — least solved, most attempted, most tickets,
  most first bloods, derived from reports the analytics page already fetched.
- **Announcement severity + audience targeting** (#44) — an info/warning/critical
  ladder, targeting to chosen teams or users, and a bell notification per
  recipient; targeted announcements bypass the shared room so the body can't
  leak to the whole competition.
- **Archived-competition auto-delete** (#26) — an opt-out retention policy that
  stamps a purge date on archive and lets the scheduler collect it.
- **A personal challenge scratchpad** (#47) — the CRDT notes surface extended to
  individual mode, private to its owner.
- Plus a contextual top-10 scoreboard chart (#53), themed scrollbars, friendly
  automation template fields (`{user_name}`, `{challenge_title}`, …), and an
  auto-dismissing announcement banner.

**v1.1.1** — **version-tagged GHCR images** (#54). Pushing a `v*` tag publishes
pinned backend/frontend images; the release frontend is built in same-origin
mode so one image works behind any single-origin proxy without a rebuild.

**v1.2.0** — the identity, accountability and trust batch
([milestone](https://github.com/tbcsec/flagpost/milestone/2)). **Shipped**
(tagged `v1.2.0`) — every issue in the milestone is closed:

- **OIDC / OAuth2 external identity** (#58, ADR-0021) — the headline feature,
  and the first item lifted off the deferred list below.
- **Personal API tokens** (#75) — self-service, `flp_`-prefixed, with
  `manage_api_tokens` as an oversight-and-revocation grant that can never mint.
- **Email verification** (#74) and **self-service add / change / clear email**
  (#106), which together close the ADR-0015 dead end where an email-less account
  could neither reset its password nor pass a verification gate.
- **Registration email-domain allowlist** (#56).
- **Rules / code of conduct** (#57) — authoring, a join gate, and recorded
  acceptance.
- **Submissions browser** (#76) — a staff dispute-resolution tab with filters and
  CSV export, behind its own `view_submissions` permission.
- **Support-ticket attachments** (#80) — screenshots on a thread, inheriting the
  visibility of the message they hang off.
- **Update check + anonymous adoption count** (#111, `PRIVACY.md`).
- Admin → Site settings refactored into tabs (#104), the react-hooks/React
  Compiler lint burn-down (#38), and fixes (#105, #124, #125, #126).

**v1.3.0** — external-auth breadth and per-surface polish
([milestone](https://github.com/tbcsec/flagpost/milestone/3)). **Shipped**
(tagged `v1.3.0`, 2026-08-04) — every issue in the milestone is closed:

- **SAML 2.0 identity providers** (#100, ADR-0022) — a second browser-redirect
  `kind` on the ADR-0021 provider framework: signature-before-trust,
  `InResponseTo`/replay/XSW defences, a persistent-NameID requirement, and an
  SP-metadata endpoint.
- **LDAP / Active Directory** (#101, ADR-0022 §5) — the first non-redirect
  `kind`: a directory bind inside `POST /api/auth/login`, tried only after local
  password verification fails, so the break-glass owner never touches a directory
  and an outage never locks everyone out. TLS-mandatory, RFC 4515-escaped search,
  stable-id subject, off the event loop under a timeout.
- **Restrict which external identities may sign in** (#118) — a per-provider
  `open`/`closed` trust posture that closes the unverified-email account-takeover
  hole for admin-configured directories.
- **Encrypted-at-rest facility for retrievable secrets** (#109, ADR-0020) —
  `utils/crypto.EncryptedString` (Fernet) covering the SMTP password and the
  OIDC/SAML/LDAP provider secrets, kept out of portable backups.
- **Alternative challenge list view** (#55), **venue/projector mode** (#77), a
  **tabbed profile page** (#113), a **magic-byte check on logo upload** (#114),
  and a single owner-provisioning helper that stamps `setup_completed_at` (#133).

**v1.4.0** — AI assistance, scale-out and authoring/UX breadth
([milestone](https://github.com/tbcsec/flagpost/milestone/4)). **Shipped**
(tagged `v1.4.0`, 2026-08-13):

- **AI assistants module** (#98, ADR-0023) — the headline feature and the last
  item lifted off the deferred list below. A fourth optional module, and the
  only one that ships **inert**: an administrator assistant and a competitor
  assistant against an operator-configured OpenAI-compatible endpoint, with the
  site master switch off by default so nothing happens until an admin turns it
  on. Read-only tools, oversight surfaces, and a competitor disclosure gate.
- **Scoreboard scale-out** (#87, #188) — a cached read model for the hot read
  paths (#87) plus delta broadcasts that cut the per-solve refetch fan-out
  (#188), lifting the known scaling limit off the unmilestoned list. The
  remaining whole-board → delta/top-N broadcast optimization is tracked but
  deliberately unbuilt (ARCHITECTURE §15).
- **Realtime performance pass** (#174–#178) — configurable/raised connection
  pool, background-lane announcement + scoreboard fan-out, parallel
  timeout-bounded room broadcast, coalesced solve bursts, and a rate-limited WS
  handshake.
- **Opt-in multi-worker** (#189, ADR-0025 / ADR-0026) — a Redis broadcast relay
  behind the connection manager plus cross-worker presence via heartbeat-TTL
  liveness, so N uvicorn workers stay correct; core-aware workers, a shared
  argon2 budget pool, and a scheduler sidecar. Off by default (single-worker
  remains the zero-infra path).
- **Automations UX** (#210, #211, #212) — human-readable condition labels,
  roomier condition boxes, and searchable name dropdowns for id fields.
- **Hidden / scheduled hints** (#213) — author a hint hidden up front, released
  later by schedule or automation.
- **Multiple-choice wrong-guess penalty** (#148) — an optional point cost on a
  wrong MC answer, surfaced in the UI with a live value drop.
- **Mass CSV user import** (#171) with optional role assignment, and a
  **fluid drag-and-resize dashboard grid** (#21) with a 2D layout.
- **Animated sign-in backgrounds** (aurora / gradient / constellation) and a
  **custom rich-text sign-in notice** (#197).
- **Built-in Google + Microsoft OIDC provider presets** (ADR-0024) — config
  data feeding the existing provider CRUD, never bundled credentials.
- **Responsive venue/projector mode** (#214), the competition-scoped
  **`manage_modules`** permission (#168), and a batch of **security hardening**
  (live-WebSocket eviction on ban/delete/team-removal, forced-safe attachment
  downloads with bounded upload memory, contained backup-import grants, MinIO
  bound to loopback, request-body cap, pool pre-ping, and announcement/freeze
  scoping fixes).

**v1.5.0** — internationalization, and a breadth batch across auth, authoring
and deployment ([milestone](https://github.com/tbcsec/flagpost/milestone/5)).
**Shipped** (tagged `v1.5.0`, 2026-08-24) — every issue in the milestone is
closed:

- **Internationalization** (#78, ADR-0029) — the headline, split into
  **#247 competitor** and **#248 admin** and delivered in full. next-intl with a
  non-routed cookie locale, a Crowdin pipeline, and a CI integrity gate that
  holds every catalog to the English source's keys and ICU placeholders/tags.
  The competitor surface was extracted and **French, Spanish and Polish went
  live** (#249); the entire admin/operator surface followed (#248). The language
  picker moved into the topbar (#251). Backend/server strings stay English by
  design. Data vocabularies (automation catalog, permission keys, enum echoes,
  theme + SSO preset catalogs) deliberately stay literal — only human-authored
  UI chrome is translated.
- **Custom certificates** (#219, ADR-0027) — an optional module: an in-app
  template editor over a server-rendered PNG (Pillow, not a headless browser),
  issuing a shareable per-participant certificate.
- **Competition status lifecycle** (#222) — an explicit
  not-started / running / ended gate with manual Start / Stop controls, the
  schedule auto-driving it, so competitor challenge and scoreboard access opens
  only while running.
- **External-auth breadth** — a **generic OAuth 2.0 provider kind** with
  built-in **GitHub and Discord** sign-in (#193, ADR-0033), where identity comes
  from a userinfo call plus a claim map rather than an ID token; and
  **multi-tenant Microsoft Entra** issuer-validation hardening (#194, ADR-0032).
- **Admin-authored custom pages** (#198, ADR-0034) — rich-text pages with their
  own sidebar entries, stored as a validated node tree and carried in the backup.
- **Post-event report generation** (#134) — a generated end-of-event report,
  streamed through the API rather than a presigned URL (#256), with the MinIO
  client region pinned so URLs sign offline (#255).
- **Authoring & onboarding** — a **master-detail challenge editor** on a
  dedicated manage route (#274), **connection info** (URL / host:port) for
  live-service challenges with a ctfcli round-trip (#262), and an
  **onboarding-style competition creation** flow that captures scoreboard,
  schedule and modules up front (#252).
- **User self-service** — **profile pictures** (upload + admin removal, audited)
  and a **self-service username change** (rate-limited, admin rename, audited).
- **Multi-instance deployment** (ADR-0031) — deployment flags and a WebSocket
  keepalive for running behind a load balancer (#259).
- **Next.js 16 migration** (#159) — Turbopack builds with the Y.js singleton
  now enforced by a build-time check rather than a webpack alias.
- **Docs & licensing** — branded, role-split **user guides** (competitor / judge
  / admin) rendered to PDF and surfaced in-app (#281), and the **Flagpost Module
  Exception** to the licence (v1.0).
- Plus fixes and hardening: per-competition state resets on a competition switch
  (#258), argon2 run at test cost with every CI job time-bounded (#207), and the
  frontend image now ships its `public/` static assets (#282).

**v1.5.1** — **relicensed to Apache 2.0** (ADR-0035). The whole platform moves
from AGPL-3.0 to the Apache License 2.0 to remove the enterprise-adoption
blocker of a copyleft licence; the Flagpost Module Exception is retired (a
permissive licence needs none), and a `NOTICE` file is added. No functional
changes. Releases up to v1.5.0 remain available under AGPL-3.0 as published.

### Planned

Summarised from the open milestones; the milestone pages are authoritative.

- **v1.6.0** — the live milestone. See the
  [milestones page](https://github.com/tbcsec/flagpost/milestones) for the
  current list.

**Deferred this cycle:** the **Major League Cyber integration** (#59) was triaged
out of v1.5.0 and closed as not-planned — its SSO half is subsumed by the
external-identity framework (a future MLC provider is a provider config, not a
bespoke path), and the feed/tracking half needs concrete MLC API scope before it
can be planned.

---

## Explicitly Deferred Past MVP

Real parts of the long-term vision that were deliberately left out of the
pre-1.0 build. Two of the items below have since moved off the deferred list
(**AI integration** and **SSO / external identity**) — kept here with their
status so the reasoning isn't lost.

- **AI integration** (Architecture §12) — both the administrator and
  competitor assistants. **Lifted, and now shipped in v1.4.0** (#98, ADR-0023):
  the condition stated here — real usage data and a settled event/data layer —
  was met, and it landed as a fourth optional module that ships inert (site
  master switch off, bring-your-own OpenAI-compatible endpoint) so no other
  feature depends on it.
- **SSO / external identity providers** (Architecture §7.7) — **lifted, and now
  complete.** OIDC/OAuth2 shipped in v1.2.0 (#58, ADR-0021): the prediction here
  held, and it plugged into the §7.7 contract as a bolt-on rather than a
  refactor. **SAML (#100) and LDAP (#101) shipped in v1.3.0** (ADR-0022,
  generalizing the provider framework): SAML as another browser-redirect
  provider, and LDAP as a credential *bind* with its own seam in the login route
  — the non-redirect seam ADR-0021 deliberately left room for. External auth is
  now OIDC + SAML + LDAP under one `IdentityProvider` model; a fourth protocol is
  a new `kind`, not a new subsystem.
- **Plugin marketplace & third-party modules** (Architecture §11) — the
  marketplace listing/discovery experience and the isolation story for
  untrusted third-party modules (Architecture §15). The manifest-driven
  module *mechanism* itself (§11.1) still matters early — the required-core
  features in Tier 1 (Challenges, Scoring, Hints, Support Tickets,
  Announcements per §11.3) can be organized through that same registration
  path for consistency, even though they're not user-toggleable. What's
  deferred here is opening that path to marketplace-distributed, untrusted
  code, not the module mechanism as a whole.
- **Multi-competition tenancy consolidation** (Architecture §6) — the
  underlying `competition_id` scoping is in Tier 0 by necessity, but the
  cross-site rollup views, global-organiser role, and multi-site
  reporting are a distinct feature for a later release once there's a
  concrete multi-site event to build it against.
