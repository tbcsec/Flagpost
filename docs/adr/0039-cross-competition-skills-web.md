# ADR-0039: Cross-competition skills web — the first participant-facing consolidation view

**Status:** Accepted (amended 2026-09-04 — admin matrix dropped; self view only)
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
