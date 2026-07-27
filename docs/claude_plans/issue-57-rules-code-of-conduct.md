# Plan: rules / code of conduct acceptance — Issue #57

Tracking issue: https://github.com/tbcsec/flagpost/issues/57

## Summary

Let administrators author a rules / code-of-conduct document with the
existing rich-text editor, at two levels: a **global** document
(site-wide, in `SiteSettings`) and an optional **per-competition
override** that supersedes it for that competition. Users must click
"I accept" for the effective document before they can join a competition
(any of: invite-code join, public self-serve join, team join/join-request).
Acceptance is recorded per user per competition and emits an event so it's
visible in the audit log. No re-acceptance is required if the text is
edited later (v1, per owner decision).

## Confirmed requirements (from issue comments)

- Scope: **global with per-competition override**.
- Acceptance must be **recorded** (who, when) and **emit an event**
  (auditable).
- **No re-acceptance** required if rules are altered after the fact.
- Gate applies at **competition join**.

## Current-state facts (from codebase research)

- `SiteSettings` (`backend/models/site_settings.py`) is a fixed-id
  singleton (`SITE_SETTINGS_ID = "site"`), fetched/created via
  `get_or_create_settings(db)` in `routers/site_settings.py`. Plain text
  fields are ordinary non-deferred columns (deferral is reserved for the
  binary `logo_data` blob) — a rules-text column belongs in the plain-column
  group.
- `routers/site_settings.py` already has a precedent for a scoped
  sub-resource with its own `GET`/`PUT` (`/site-settings/operational`),
  same `manage_site_settings` permission, and an event payload convention
  of `{"section": "..."}` — a `/site-settings/rules` pair (or folding into
  the existing `PUT` — implementer's call) can follow this exactly.
- Competition join has **three** call sites, not one:
  - `POST /api/competitions/join` (`join_by_code`) and
    `POST /api/competitions/{id}/join` (`join_competition`) — both route
    through a shared `_join()` helper in `routers/competitions.py`.
  - `POST /api/competitions/{id}/teams/join` (`join_team`) in
    `routers/teams.py` — team-mode join, does **not** go through `_join()`,
    calls `ensure_participant_role` directly, and has a separate
    pending-approval branch (files a `TeamApplication` without granting
    membership yet, for `approval_required` teams).
  - A gate must cover all three; centralizing the check in one shared
    helper (called from `_join()` and from `join_team`) is the DRY option
    the research flagged — whether that helper belongs in
    `auth/membership.py` alongside `ensure_participant_role` needs
    confirming against that file's current contents during implementation.
- Recent `Competition` field additions (e.g. `paused`) follow: model column
  → migration (`YYYY-MM-DD_<revid>_<desc>.py`, chained off the current
  head) → `CompetitionCreate`/`Update`/`Out` schema fields → explicit
  assignment in the create/update routers → a field on the tabbed
  `competition-settings-form.tsx` (General/Schedule/Challenges/Modules
  tabs, form stays mounted across tabs so switching never drops an edit).
- Per-user auxiliary-table precedent: `TeamMembership` — a
  `CompetitionScopedMixin` + `TimestampMixin` model with a composite
  `UniqueConstraint("competition_id", "user_id", ...)`. A `rules_acceptances`
  table should follow this exact shape (not the `PasswordResetToken`
  shape, which is site-wide/tokenised rather than competition-scoped).
- Both join call sites already load the full `Competition` row before
  granting membership, and `get_or_create_settings(db)` is already
  imported into `competitions.py` — so both the override text and the
  global fallback are cheaply available at the enforcement point with no
  new plumbing.
- Event catalog: `backend/utils/event_catalog.py`'s `EVENT_TYPES` tuple —
  append `competition.rules_accepted`; it's auto-included in
  `TRIGGERABLE_EVENTS` (only `automation.*`/`platform.*` are excluded), so
  it becomes an automation trigger for free — worth surfacing to the owner
  since it wasn't asked for explicitly.
- `emit()` lane: this is a simple audit-log write (like
  `competition.member_joined`), so it uses the **default foreground**
  lane, not `background=True`.
- Rich text: the existing `RichTextEditor` (`components/ui/rich-text-editor.tsx`)
  round-trips **ProseMirror JSON** (`RichTextDoc`), not HTML — backend
  storage for both the global and override rules text should be a JSON
  column, matching `Challenge.description`.

## Implementation steps

### Backend

1. **Migration** (single migration, chained off the current head):
   - `site_settings.rules_text` — JSON, nullable (no rules configured =
     no gate).
   - `competitions.rules_override` — JSON, nullable (falls back to global
     when null).
   - New table `rules_acceptances`: `id` (uuid pk), `user_id` (FK `users.id`,
     `ondelete="CASCADE"`), `competition_id` (FK `competitions.id`,
     `ondelete="CASCADE"`), `accepted_at` (`UtcDateTime`), unique constraint
     on `(user_id, competition_id)`.
2. **Model**: `RulesAcceptance(Base, CompetitionScopedMixin, TimestampMixin)`
   in a new `backend/models/rules_acceptance.py` (or folded into
   `competition.py`), mirroring `TeamMembership`'s shape.
3. **Event catalog**: add `competition.rules_accepted` to `EVENT_TYPES`.
4. **Schemas**: `rules_text: RichTextDoc | None` on `SiteSettingsOut`/
   `SiteSettingsUpdate` (or a dedicated `RulesSettingsOut/Update` if it's
   split into its own sub-resource); `rules_override: RichTextDoc | None`
   on `CompetitionCreate`/`Update`/`Out`.
5. **New endpoints** (competition-scoped, `backend/routers/competitions.py`
   or a small new `routers/rules.py` mounted by the `competitions` plugin):
   - `GET /api/competitions/{id}/rules` — authenticated (no special
     permission — any user en route to joining needs this), returns the
     effective text (`competition.rules_override ?? site_settings.rules_text`)
     and whether the current user has already accepted it
     (`RulesAcceptance` lookup) so the frontend can skip the modal on
     repeat visits.
   - `POST /api/competitions/{id}/rules/accept` — authenticated, idempotent
     (unique-constraint upsert-or-ignore), creates the acceptance row and
     emits `competition.rules_accepted` with `{competition_id, user_id}`.
6. **Join-flow gate**: a shared `require_rules_accepted(db, competition, user)`
   check, raising a distinguishable error (e.g. HTTP 403 with
   `{"detail": "rules_not_accepted"}`) when effective rules text exists and
   no acceptance row is present, called at the **top** of `_join()`,
   `join_by_code`/`join_competition` (via `_join`), and `join_team` —
   including before the pending-approval branch in `join_team`, so filing
   a join *request* also requires acceptance, not just final membership
   grant.
7. **Site settings routes**: extend the existing `PUT /api/site-settings`
   (or add a `/site-settings/rules` sub-resource, matching the
   `/operational` precedent) gated `manage_site_settings`, emitting
   `site.settings_updated` with a `{"section": "rules"}` marker.
8. **Competition routes**: `rules_override` follows the same
   create/update assignment pattern as `paused`/`brackets`, gated
   `edit_competition`.

### Frontend

9. **Hook module** `frontend/src/lib/hooks/use-rules.ts`:
   `useCompetitionRules(competitionId)` (GET, gates on being about to
   join) and `useAcceptRules(competitionId)` (POST mutation,
   invalidates the rules query).
10. **`RulesAcceptModal`** component (`components/competitions/rules-accept-modal.tsx`):
    read-only render of the `RichTextDoc` (reuse/extract a read-only
    variant of `RichTextEditor`, or the same renderer challenge
    descriptions already use for display), an "I accept" checkbox, and a
    disabled-until-checked Accept button that calls the accept mutation.
11. **Wire into join flows**:
    - `frontend/src/app/(app)/lobby/page.tsx` — both the invite-code form
      (`onJoinByCode`) and the public-competition "Join" button
      (`useJoinCompetition`): before firing the join mutation, fetch rules
      via `useCompetitionRules`; if unaccepted rules exist, show the modal
      and only fire the join mutation after `useAcceptRules` resolves.
    - `frontend/src/components/teams/team-panel.tsx`'s `JoinOrCreate`
      (team join-by-code form, `useJoinTeam`) — identical gating before
      submit.
12. **Admin authoring UI**:
    - Competition Settings (`competition-settings-form.tsx`) — a new
      "Rules" field (or its own tab, if the General tab is already dense)
      with `RichTextEditor` bound to `rules_override`, gated `edit_competition`.
    - Admin → Site settings — a "Rules" section (Appearance or a new tab,
      following the `/operational` split precedent) with `RichTextEditor`
      bound to the global `rules_text`, gated `manage_site_settings`.

### Tests

13. Backend: pytest coverage for all three join paths (code join, public
    join, team join incl. the approval-pending branch) rejecting without
    acceptance and succeeding after; acceptance idempotency; event
    emission and audit-log visibility; override-vs-global text resolution.
14. Frontend: Vitest coverage for the modal's gating logic (shows only
    when unaccepted text exists, blocks submit until checked+accepted).

## Files touched (expected)

- New migration under `backend/alembic/versions/`
- `backend/models/site_settings.py`, `backend/models/competition.py`,
  new `backend/models/rules_acceptance.py`
- `backend/utils/event_catalog.py`
- `backend/schemas/site_settings.py`, `backend/schemas/competition.py`,
  new `backend/schemas/rules.py`
- `backend/routers/site_settings.py`, `backend/routers/competitions.py`,
  `backend/routers/teams.py` (or a shared helper module both import)
- `frontend/src/lib/hooks/use-rules.ts` (new)
- `frontend/src/components/competitions/rules-accept-modal.tsx` (new)
- `frontend/src/app/(app)/lobby/page.tsx`
- `frontend/src/components/teams/team-panel.tsx`
- `frontend/src/components/competitions/competition-settings-form.tsx`
- Admin → Site settings page/component
- Corresponding backend pytest + frontend Vitest specs

## Open Questions

- The issue's proposed solution mentions administrators can "specify if
  students must click an 'I accept' box" — the confirmed requirements
  (record + gate at join) read as acceptance always being mandatory
  whenever rules text is configured. Is there also a wanted **display-only**
  mode (rules shown, no forced checkbox, no join-blocking) for organisers
  who just want to surface information without a hard gate, or is
  "rules text is set ⇒ acceptance is always mandatory at join" the full
  v1 scope?
- Should staff members (who can already see/edit the rules text) be
  exempted from the accept gate when they join their own competition, or
  go through the same flow as competitors?
- For team-mode competitions with `approval_required`, this plan gates
  rules acceptance at the point a user **files** a join request, not only
  at the point a captain **approves** it. Confirm that's the intended
  "join" moment.
- Known consequence of "no re-acceptance if rules are altered": since
  acceptance rows aren't tied to a text version, a competition that later
  adds a **new** per-competition override (where none existed before) will
  not prompt already-accepted (global-rules) members to re-accept the more
  specific text, even though the effective document changed. Is that
  acceptable for v1, or should adding/changing an override force
  re-acceptance as a narrower exception to the "no versioning" rule?
