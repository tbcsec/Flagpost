# Roadmap: MVP

This document breaks `ARCHITECTURE.md` and `VISION.md` down into an ordered,
actionable feature list for a viable MVP.

**Scope of this MVP**: a basic, well-run competition management tool with
the modern frontend already designed — not the automation engine, not AI
assistance, not the plugin marketplace, not multi-site tenancy. Those are
real parts of the long-term vision, but none of them are required for an
organiser to run a competition better than a spreadsheet + Discord today.
Where a feature is deferred, it's noted explicitly so nothing gets lost.

Tiers are ordered by importance: **Tier 0 is scaffolding nothing else can
be built without; Tier 1 is what makes the platform minimally usable to run
a real competition; Tier 2 is what makes it good enough that organisers
prefer it to what they're using now; Tier 3 is polish worth doing before a
public launch, but not before Tier 1/2.** Within each tier, items are
listed in the order they should be built — later items in a tier often
depend on earlier ones.

---

## Tier 0 — Foundation

**Status: ✅ complete (tagged `tier-0`).**

Nothing user-facing yet. Get this wrong and everything built on top of it
gets expensive to fix later; get it right and every later tier is faster
to build, not slower.

1. **Auth & RBAC** — registration, login, session handling (local
   password auth per Architecture §7.7 — no SSO at this stage, see
   Explicitly Deferred below), and the role and permission model from
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
changes from the list below carried through: **#17 (challenge
lifecycle) is deferred to a future tier** (needs more design), and **#20 is
rescoped from per-competition to site-wide theming** (the
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
    **Deferred to a future tier** (owner decision) — wants more design
    first; not built in Tier 2.
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

**Status: in progress**, built phase-by-phase per `docs/claude_plans/phase_3.md`
(automation-first, full spec). Shipped so far: Phase 0 (notification-center +
event-dispatch groundwork, ADR-0012); the **full automation engine (#25)**
across Phases 1–3 — the engine + all eight §5.3 actions + the first optional
per-competition-toggleable module (Phase 1), webhook hardening (Phase 2,
ADR-0013), and the §5.5 visual rule builder (Phase 3); **feedback/survey (#22)**
(Phase 4, the second optional module + automation glue); **challenge & team
analytics (#23)** (Phase 5, the third optional module); **dashboard
drag-and-drop (#26)** (Phase 6, per-user layout customization on the Tier-2
widget registry); and **collaborative rich-text / CRDT editing (#27)** (Phase 7,
Y.js team scratchpad + staff ticket notes, ADR-0014). Remaining: onboarding
(#24) and the a11y/optimization pass (#28).

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
    to skip, very noticeable when skipped.
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
    check scoreboards from their phones), a full optimization pass.

---

## Explicitly Deferred Past MVP

Real parts of the long-term vision, intentionally not in this roadmap:

- **AI integration** (Architecture §12) — both the administrator and
  competitor assistants. Needs real usage data and a settled event/data
  layer to be useful rather than decorative.
- **SSO / external identity providers** (Architecture §7.7) — LDAP, SAML,
  OAuth. Local password auth is the only login method through public
  release; the auth module contract in §7.7 is built to make SSO a
  bolt-on later rather than a refactor, but the providers themselves
  aren't built until there's real demand for a specific one.
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
