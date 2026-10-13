# ADR-0039: Cross-competition skills web — the first participant-facing consolidation view

**Status:** Accepted (amended 2026-09-04 — admin matrix dropped; re-amended 2026-10-13 — admin matrix reinstated and enriched, #435)
**Date:** 2026-09-04
**Architecture reference:** `ARCHITECTURE.md` §6.3 (tenancy scoping — the
sanctioned cross-competition reads). Implements #364.

## Context

Flagpost is strictly `competition_id`-scoped (§6.2): every query and route names
a competition, and "multi-competition consolidation views / cross-site rollups"
sit on the **Explicitly Deferred** list (`ROADMAP.md`, `.claude/CLAUDE.md`).
Exactly two reads are sanctioned exceptions today, both narrow: the site
`GET /api/admin/overview` (Administrator-only platform totals, "the one
sanctioned cross-competition read", §6.3) and `GET /api/me/certificates` (a
participant's own released certificates across every event, self-scoped by route
shape).

#364 asks for a **skills web** in the HackTheBox mould: each skill axis starts at
0 and grows *outward* as a competitor solves challenges in that category —
unbounded, monotonic, and explicitly **not** `solved ÷ total`. The owner's intent
(triaged 2026-09-04) is that a competitor's web **keeps growing across every
competition they play**, so the feature is cross-competition by definition. That
makes it the deliberate third sanctioned consolidation read, and the first that
is *participant-facing* rather than an admin total — hence an ADR, not a quiet
build-around of the deferral.

The tension the design has to resolve: a "skill" is a challenge **category**, but
category (and tag, and difficulty) vocabularies are **100% per-competition**
(`models/challenge.py`, `models/competition.py`) — two events can name categories
anything, and there is no site-global taxonomy to hang stable radar axes on.

## Decision

Build a cross-competition skills web as a new optional `skills` module.

1. **Skill key = the normalized category name** (`name.strip().lower()`), folded
   to the normalized key **in Python, not SQL** (the ADR-0006 parity convention
   `admin_overview`/`analytics` already use), so same-named categories across
   competitions — and across casing — merge into one axis. A challenge with no
   category is excluded. There is no site-global taxonomy; the category *name* is
   the only thing that links a skill across events. (An admin alias/merge map for
   naming drift is a future enhancement, not v1.)

2. **Score = `+1` per distinct awarded solve** (`is_correct AND NOT
   is_duplicate`). `points` and `difficulty` are per-competition vocab and do
   **not** normalize across events — summing a 500-pt easy web box in one event
   with a 50-pt hard pwn box in another is a meaningless number — so a count is
   the only cross-competition-composable weight, and it is exactly the HTB "one
   notch per box" model. The weight lives behind a single `solve_weight()` seam so
   a later change to points/difficulty is one line.

3. **Credit the submitting `user_id`.** It is set on every submission in both
   individual and team mode, so a per-**user** web that spans every competition is
   a clean join. In team mode this credits the submitter only, not every teammate
   who worked the challenge — a deliberate v1 tradeoff (all-members-at-solve-time
   needs membership-at-that-instant reconstruction; deferred). Teams are
   per-competition and cannot aggregate across events, so the web is inherently a
   *user* profile.

4. **Two reads, no new permission.**
   - `GET /api/me/skills` — the caller's own web, **auth-only** (the route shape
     is the authorization, like `/api/me/certificates`).
   - `GET /api/admin/skills` — the users × skills matrix, gated on the existing
     **`view_global_analytics`** (Scope.GLOBAL, Administrator-only), **paginated
     over users**.
   Both responses carry their axis labels explicitly; the frontend never infers
   the skill set.

5. **A new `skills` module** (`plugins/skills/`), not the `analytics` module —
   analytics is per-competition (routes are `/api/competitions/{id}/…`, toggled
   per competition, gated by `view_competition_analytics`) and this is site-wide.
   Optionality is a single **`site_settings.skills_enabled`** (default **on**),
   since a cross-competition feature can't be a `competition_modules` toggle; when
   off, both routers 404 (the certificates `_guard` pattern).

6. **On-demand aggregate + a process-global TTL cache**, mirroring
   `utils/scoreboard_timeline.py`, with a single `invalidate_skills()` that drops
   the whole cache on any solve/category change — it cannot key by competition, so
   it over-invalidates, which is a cheap dict delete (the scoring plugin's own
   rationale). A precomputed per-`(user, skill)` rollup table is the **scale
   follow-up** (as #87 stages the scoreboard), not v1.

7. **Privacy: self + admin only.** A competitor sees their own web; an
   Administrator sees the matrix. Other-user and public skill profiles are
   deferred. A cross-competition personal profile is new personal data — recorded
   in `PRIVACY.md` — but it is a derived read over data the site already holds and
   adds no outbound flow.

## Consequences

- **Positive:** a competitor gets a durable skill profile that grows across every
  event, not a per-competition snapshot that resets (retention/engagement, the
  §364 ask); organizers see skill coverage and gaps site-wide; it reuses existing
  `submissions` data with **no new instrumentation** and a single additive
  `add_column` migration (the site-settings flag).
- **Negative / cost:** it is the first cross-competition *scan* — bounded for now
  by the cache, and it is why the rollup table is pre-named as the scale path;
  category-**naming drift** fragments a skill across events (mitigated later by an
  alias map, and the `+1`/name choices keep the API shape stable when that lands);
  team-mode undercounts non-submitting teammates; cache invalidation is coarse
  (any solve drops every user's cached web).
- **Forecloses:** little — because axis labels are explicit in the response and
  the skill key is isolated, swapping the normalized-name key for a real
  site-global taxonomy later does not change the API contract or the frontend.

## Alternatives considered

- **Per-competition matrix only.** The safe, non-deferral-reversing option (fits
  §6.2, the `analytics` module, `view_competition_analytics`). Rejected by the
  owner: it can't express a web that *grows across events*, which is the point.
- **`solved ÷ total` (a bounded coverage %).** Rejected: the owner wants an
  unbounded web "not limited by the challenges available", i.e. HTB-style
  accumulation, not saturation.
- **Points- or difficulty-weighted score.** Rejected: both are per-competition
  and not normalized, so cross-event sums are meaningless (see Decision #2).
- **A site-global skill taxonomy with per-category mapping.** The robust
  long-term answer to naming drift, but it adds an authoring surface (a canonical
  skill list + a mapping UI). Deferred: the normalized-name key is the lean v1 and
  a taxonomy can layer on without breaking the contract.
- **Extend the `analytics` module.** Rejected: analytics is competition-scoped and
  per-competition-toggled; a site-wide cross-competition read needs its own home
  and its own optionality.

## Amendment: admin matrix dropped for now (2026-09-04)

Decision #4 above shipped **two** reads: the self view (`/api/me/skills`) and an
Administrator users×skills **matrix** (`/api/admin/skills`, `view_global_analytics`).
On review the owner decided **against the admin matrix for now** and it has been
removed — the endpoint, the `compute_skill_matrix` read model, the `/admin/skills`
page and its nav entry. The feature ships as the **participant self view only**.

This narrows, but does not change, the ADR's core: the skills web is still a
sanctioned cross-competition read, just a purely **self-scoped** one (the route
shape is the authorization, exactly like `/api/me/certificates`) — so it no longer
even touches `view_global_analytics`. #364 asked for an admin view; that part is
deliberately deferred (owner decision), and the read model keeps the per-user
shape that a matrix would rebuild on, so re-adding it later is additive.

## Amendment: admin matrix reinstated (2026-10-13, #435)

The owner green-lit the deferred half. The matrix returns exactly as last
reviewed — reverse-applied from the drop commit on #384's branch — under the
same gates the first amendment described: `view_global_analytics` (GLOBAL,
Administrator-only by default) on `GET /api/admin/skills`, 404 while the
site-wide `skills_enabled` switch is off, paginated (50 default / 200 max) over
the shared TTL-cached read model. The additive re-add the first amendment
predicted is what happened; the privacy surface is named in `PRIVACY.md`. The
rollup table remains the scale follow-up, out of scope here.

## Amendment: the matrix enriched — weighted points, coverage, percentile (2026-10-13, #435)

Raw solve counts conflate volume with proficiency, so each matrix cell now
carries three labeled signals instead of one number:

- **weighted** — Σ ``Submission.points_awarded``: the value priced at solve time,
  so dynamic-decay rarity is already in the row. This is the "sum a column"
  weighting the ``solve_weight`` seam anticipated. The original caveat stands:
  **points are per-competition vocab and do not normalize across events** — raw
  weighted values are context, never the cross-user comparator.
- **solved / available** — coverage against genuine opportunity: published
  challenges in the competitions the user is a *member* of (any competition-
  scoped role). Clamped so a challenge unpublished after a solve can't read as
  ``3/0``; a category the user never had access to renders as absence, not zero.
- **pct** — the percentile of ``weighted`` within the column over every tracked
  user. This is the scale-free comparator, rendered as the heat map.

Plus a per-column **population** footer (solver count, mean weighted — the
"where is the community weak" read), server-side column sorting (truthful
across pages), and a CSV export (``csv_safe``-escaped; display names are
competitor-controlled). The self view (``/api/me/skills``) is unchanged.
Invalidation now also rides ``challenge.published`` and
``competition.member_joined``, since opportunity moves cells. A composite
"proficiency index" was considered and rejected: three explainable signals over
one opaque number. Efficiency signals (attempts/hints per solve), first-blood
badges and time-windowing are the deliberate v2 line.

## Amendment: matrix v2 — efficiency, first bloods, windows, drill-down (2026-10-13, #440)

Four additions over the #435 enrichment, all derived (no schema change):

- **Efficiency counts** per cell: ``attempts`` (every non-duplicate graded
  submission in the category — struggle on never-solved challenges included,
  deliberately: it is signal) and ``hints`` (reveals taken). Served as counts;
  the UI derives per-solve ratios.
- **First bloods** are a **historical fact**: the earliest awarded submission
  per challenge (ties broken by ``created_at`` then id for SQLite/Postgres
  determinism), derived over **all time** and never recomputed inside a window
  — otherwise the second solver would be crowned once the true first scrolls
  out. A window only decides which *earned* first bloods are counted.
- **Activity windows** (``all``/``365``/``90``/``30`` days) bound solves,
  attempts and hints — never opportunity (``available`` is always current).
  The allowlist is the cache-key design: windows key the cache
  (``matrix:<window>``), so an open-ended date range would grow the keyspace
  per request and is rejected (422).
- **Admin drill-down** (``GET /api/admin/skills/users/{user_id}``): one user's
  per-skill stats plus their recent solves with attempts/hints/first-blood
  context (capped at 200). Same gates as the matrix; an unknown user is an
  undisclosing 404, and misses are never cached (id probing must not grow the
  cache). This is a deeper per-user read than the matrix — named in
  ``PRIVACY.md``.
