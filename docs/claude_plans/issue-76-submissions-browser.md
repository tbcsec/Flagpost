# Plan: submissions browser — Issue #76

Tracking issue: https://github.com/tbcsec/flagpost/issues/76

## Summary

A judge/admin-facing, paginated, filterable table of raw flag-submission
attempts (correct, incorrect, and duplicate), showing the exact submitted
payload and exact timestamp, so staff can resolve disputes without
triangulating between the audit log and aggregate analytics. Lands as a
new **Submissions** tab on the existing `/analytics` page. Pure read model
over the existing `submissions` table — no migration, no new event.

## Confirmed requirements (from issue comments)

- Lives as a tab on `/analytics`.
- Available to **Judge and above**.
- Filters: correct / incorrect / duplicate, time range, free-text payload
  search.
- Pagination required — "expecting a lot of entries."

## Current-state facts (from codebase research)

- `Submission` (`backend/models/submission.py`) already has everything
  needed: `challenge_id`, `user_id`, `team_id` (null in individual mode),
  `value` (raw submitted text), `is_correct`, `is_duplicate`,
  `points_awarded`, plus `competition_id` and `created_at` (the exact
  timestamp). **"Duplicate" is already modeled** as "correct flag, but the
  subject had already solved that challenge" (`is_duplicate = correct and
  already_solved`, set in `routers/submissions.py`) — it is **not**
  "identical payload value submitted before." That distinction matters for
  the filter's exact semantics (see Open Questions).
- `backend/routers/submissions.py` only has the write path (the flag-submit
  endpoint) — no read/list endpoint exists yet anywhere in the codebase.
- `backend/routers/analytics.py` + `backend/utils/analytics.py` are the
  right home: existing `/analytics/challenges` and `/analytics/teams`
  routes are gated `require_permission("view_competition_analytics")` and
  mounted through the optional `analytics` module (`is_module_enabled`
  check per-request, 404 when the competition has it disabled). A new
  submissions route should follow this identical shape.
- **Judge already holds `view_competition_analytics`** (`JUDGE_PERMISSIONS`
  in `backend/auth/permissions.py`; Administrator inherits everything via
  `ADMINISTRATOR_PERMISSIONS`). Since the feature is explicitly framed as
  an analytics tab and the owner's requirement is "Judge and above," reusing
  this existing permission is the lowest-friction choice and needs no
  `auth/seed.py` change (flagged as a trade-off in Open Questions).
- The audit-log viewer is the correct precedent to copy, not the existing
  `/analytics` tables: `backend/routers/audit_log.py` uses **offset/limit**
  pagination (`limit: Query(50, ge=1, le=200)`, `offset: Query(0, ge=0)`),
  a shared `_apply_filters(stmt, ...)` helper applied to both a `count(*)`
  and the paged `select`, `order_by(created_at.desc(), id.desc())`, and a
  companion distinct-values endpoint for filter dropdowns. Its response
  shape — `AuditLogPage { items, total, limit, offset }` — is the
  established "shape" for a list endpoint and should be mirrored as
  `SubmissionPage`. The existing `/analytics` tables instead paginate
  client-side over an already-fully-fetched array (`useDataTable`) — not
  appropriate here given the owner's explicit "expecting a lot of entries."
- Free-text search: audit-log's `q` does `ilike` over `event_name`/payload;
  the direct analog here is `Submission.value.ilike(f"%{q}%")`.
- Frontend precedent for the filter UI: `frontend/src/app/(app)/admin/events/page.tsx`
  (the audit-log page) — `draft` vs `applied` filter state, `EntityCombobox`
  for team/user pickers (backed by `useTeams`/`useUsers`), `datetime-local`
  inputs converted to ISO, Apply/Reset buttons, and a manual Previous/Next
  pager computed from `total`/`offset`/page-size — not the `useDataTable`
  client-side helper.
- `/analytics/page.tsx` currently has **no tabs** — it's one page
  (Overview stats + two client-paginated tables). This will be the first
  use of tabs there. The dependency-free `Tabs` primitive
  (`components/ui/tabs.tsx`) already exists and is used exactly this way
  in Competition Settings (form/content stays mounted-but-hidden across
  inactive tabs) — directly reusable.
- `use-analytics.ts` is a thin two-hook module today (`useChallengeAnalytics`,
  `useTeamAnalytics`); a new submissions hook should follow the audit-log
  hook's server-paginated pattern (`keepPreviousData`, filter object in the
  query key) rather than extend those two.

## Implementation steps

### Backend

1. **Schema** (`backend/schemas/submission.py`, new or extended): a
   `SubmissionCorrectness` enum/literal — `correct` (`is_correct` and not
   `is_duplicate`), `incorrect` (not `is_correct`), `duplicate`
   (`is_correct` and `is_duplicate`) — three mutually-exclusive buckets
   matching the owner's proposed filter set; `SubmissionOut` (challenge_id,
   user_id, team_id, value, correctness, points_awarded, created_at);
   `SubmissionPage { items, total, limit, offset }` mirroring `AuditLogPage`.
2. **Route** `GET /api/competitions/{id}/analytics/submissions` in
   `backend/routers/analytics.py`, gated `require_permission("view_competition_analytics")`
   + the existing `_competition_or_404` module-enabled check. Query params:
   `challenge_id`, `user_id`, `team_id`, `correctness`, `since`, `until`,
   `q` (free text over `value`), `limit`/`offset` (same bounds as
   audit-log).
3. **Filter helper**: `_apply_submission_filters(stmt, ...)` applied to
   both the `count(*)` and the paged `select`, `order_by(created_at.desc(), id.desc())`
   — copy the audit-log router's structure directly.
4. **Challenge/subject display names**: resolve `challenge_id`/`user_id`/
   `team_id` to display names **client-side** via the already-cached
   `useChallenges`/`useTeams`/`useUsers` hooks (the same `categoryName(id)`-
   style lookup pattern the challenges page already uses), rather than
   joining/denormalizing names into the response — keeps the endpoint a
   thin, cache-friendly read over `submissions` only.
5. **No new permission, no migration, no new event** — read-only over
   existing data, same footprint as `/analytics/challenges` and
   `/analytics/teams`.

### Frontend

6. **Hook**: `frontend/src/lib/hooks/use-submissions.ts` —
   `useSubmissionBrowser(competitionId, filters)`, react-query with
   `keepPreviousData: true` and the filter object in the query key,
   following `useAuditLog`'s shape.
7. **Tabs on `/analytics`**: wrap existing content as an "Overview" tab,
   add a "Submissions" tab, using the existing `Tabs` primitive
   (mounted-but-hidden convention, matching Competition Settings).
8. **`SubmissionsBrowser` component** (`components/analytics/submissions-browser.tsx`):
   draft/applied filter state (mirroring `admin/events/page.tsx`) —
   `EntityCombobox` for team/user (backed by `useTeams`/`useUsers`), a
   challenge `<Select>` (backed by `useChallenges`), a correctness
   `<Select>` (All/Correct/Incorrect/Duplicate), `datetime-local`
   since/until inputs, a free-text search input, Apply/Reset buttons, and
   a table (challenge title, subject name, payload value, correctness
   badge, exact timestamp) with a manual Previous/Next pager driven by
   `total`/`offset`/page-size (not `useDataTable`).
9. **Tests**: backend pytest for filter combinations + pagination bounds +
   permission gating (Judge sees it, Participant gets 403, disabled
   `analytics` module 404s); frontend Vitest for filter-state transitions
   and empty/paginated render states.

## Files touched (expected)

- `backend/schemas/submission.py` (new/extended)
- `backend/routers/analytics.py`
- `frontend/src/lib/hooks/use-submissions.ts` (new)
- `frontend/src/components/analytics/submissions-browser.tsx` (new)
- `frontend/src/app/(app)/analytics/page.tsx`
- Corresponding backend pytest + frontend Vitest specs

No migration, no new permission, no new event.

## Open Questions

- The data model's existing "duplicate" flag means *"correct flag, but
  already solved"* — not *"this exact payload string was submitted
  before."* For a dispute like "did the team actually submit the right
  flag at time Y," that's usually the meaning that matters and is already
  covered by `is_correct`/`created_at`. Is the "duplicate" filter bucket
  as currently modeled (repeat-correct-submission) sufficient, or is there
  also a want for same-value-repeat detection across *incorrect* attempts
  (which doesn't exist today and would be new logic, not just a read
  model)?
- Reusing the existing `view_competition_analytics` permission means
  anyone who can see aggregate analytics can also see raw per-submission
  payloads (a broader grant than a hypothetical analytics-only role might
  want). Acceptable, or should this be a narrower new permission (e.g.
  `view_submissions`) that Judge/Admin hold by default but that could
  later be granted independently of aggregate analytics?
- Should the browser support exporting the filtered rows (CSV), similar to
  the feedback module's response export? Not requested in the issue, but
  flagged since it's a natural follow-on for the stated "resolve a
  dispute" use case and a nearby precedent already exists.
