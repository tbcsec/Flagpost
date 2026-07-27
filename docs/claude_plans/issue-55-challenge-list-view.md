# Plan: alternative (list) challenge view — Issue #55

Tracking issue: https://github.com/tbcsec/flagpost/issues/55

## Summary

Add a per-user-persisted toggle on the challenges browse page
(`frontend/src/app/(app)/challenges/page.tsx`) that switches between the
existing card grid (stays default) and a new list view: challenges grouped
by category into collapsible sections (collapsed by default), each row
showing name / points / category / difficulty, with a padlock indicator on
locked challenges. Frontend-only — no backend or API changes.

## Confirmed requirements (from issue comments)

- List row fields: challenge name, points, category, difficulty.
- Categories default to **collapsed**.
- View toggle (card/list) persists **per user, across sessions**.
- Locked challenges show a padlock icon; the existing All/Available/Locked
  filter continues to apply in both views.

## Current-state facts (from codebase research)

- `frontend/src/app/(app)/challenges/page.tsx` fetches `useChallenges` +
  `useCategories`, filters into a flat array via `useMemo` (category filter
  + availability filter), then paginates that flat array through
  `useDataTable` (`grid.rows`) and renders one flat card grid. **There is no
  existing "group by category" render path** — categories today only drive
  the filter chips, each card just labels its own category inline via a
  `categoryName(id)` helper.
- The `Challenge` object already carries everything a list row needs —
  `title`, `value`/computed points, `category_id`, `difficulty`, `locked`,
  `state` — via `use-challenges.ts` / `frontend/src/lib/types.ts`. No new
  endpoint or hook field is required.
- Locked indicator convention today is a plain `🔒` emoji glyph inside the
  existing `Badge` component (`<Badge variant="outline">🔒 Locked</Badge>`)
  — no icon library is installed (no lucide-react, no radix icons). The
  list view should reuse this glyph for visual consistency rather than
  introduce a new icon dependency.
- Persisted per-user client preference precedent: `frontend/src/stores/auth.ts`
  hand-rolls localStorage persistence (no zustand `persist` middleware) —
  a `paletteOverride` field with a `setPaletteOverride` action that writes
  `window.localStorage` synchronously (wrapped in try/catch for
  SSR/private-mode), a `hydratePaletteOverride()` called once from a mount
  `useEffect` in `theme-applier.tsx` (since the store must start SSR-safe
  at `null`/default). This is a **local-device** preference (not synced to
  the user's backend profile) — the same model fits a card/list toggle and
  matches "persists across sessions" without requiring a backend field.
- No collapsible/accordion primitive exists in `frontend/src/components/ui/`
  and no Radix accordion/collapsible package is installed. Build a small
  local component rather than add a dependency — the codebase already does
  manual disclosure state elsewhere (plain `useState` boolean/set + a
  chevron), e.g. the `managing` toggle and `palette-menu.tsx`'s open-state
  handling.
- Category order: `categories.data` has no explicit client-side sort today;
  list-view group order should just use the same order the existing filter
  chips use (`categories.data` iteration order), so it stays visually
  consistent with the chip row.
- All styling must go through existing Tailwind/CSS-var tokens
  (`frontend/src/app/globals.css` `[data-palette]` blocks) — no raw hex.

## Implementation steps

1. **View-mode store** — add a `viewMode: "card" | "list"` field + a
   `setViewMode`/`hydrateViewMode` pair to `frontend/src/stores/auth.ts`
   (or a small sibling store if keeping `auth.ts` focused on auth state is
   preferred — final call left to the implementer), mirroring
   `paletteOverride` exactly: `localStorage` key `fp:challenges-view`,
   SSR-safe default (`"card"`), hydrate-on-mount in the challenges page.
2. **View toggle control** — a small segmented control (reuse `Button`
   variants, no new primitive needed) near the existing availability
   filter row in `page.tsx`, wired to the store.
3. **Collapsible category section component** — new
   `frontend/src/components/challenges/challenge-category-list.tsx` (or
   similar): takes a category + its filtered challenges, renders a header
   button (category name, solved/total count — reuse the same count logic
   already computed for the filter chips) that toggles a collapsed/expanded
   `useState`, defaulting to collapsed; expanded state does **not** need to
   persist (issue is silent on this — flagged below as an open question,
   defaulting to session-only/component state, reset on navigation).
4. **List row component** — `frontend/src/components/challenges/challenge-list-row.tsx`:
   a single-line/compact row (name, points, difficulty badge, padlock `🔒`
   badge when `locked`) that calls the same `setOpen(ch)` the cards use, so
   the existing challenge detail dialog is reused unchanged.
5. **Wire into `page.tsx`** — when `viewMode === "list"`, group the same
   `grid.rows`-equivalent filtered set (reconsider: grouping needs the full
   filtered set per category, not the paginated slice — the list view will
   likely paginate *within* each category's collapsible body, or drop
   `useDataTable` pagination in favor of "collapsed by default" acting as
   the volume control; recommend the latter for v1 to avoid mismatched
   pagination-vs-grouping semantics) by `category_id` using
   `categories.data`, render one `ChallengeCategoryList` per category
   (skip empty categories after filtering), each containing
   `ChallengeListRow`s. When `viewMode === "card"`, render exactly the
   current grid unchanged.
6. **Availability filter interplay** — the list view consumes the same
   `visible` filtered array the card grid does, so the All/Available/Locked
   chips continue to work identically; only the render path branches on
   `viewMode`.
7. **Tests** — add/extend `frontend` Vitest coverage for the new
   grouping/collapse logic (pure function extracted for "group challenges
   by category" so it's unit-testable independent of rendering) and a
   render test asserting collapsed-by-default + locked badge presence.

## Files touched (expected)

- `frontend/src/app/(app)/challenges/page.tsx` (view toggle wiring, branch
  render path)
- `frontend/src/stores/auth.ts` (or new store) — `viewMode` persistence
- `frontend/src/components/challenges/challenge-category-list.tsx` (new)
- `frontend/src/components/challenges/challenge-list-row.tsx` (new)
- Corresponding Vitest specs under the same directories

No backend files, no migration, no new event — purely a frontend, additive
change.

## Open questions

- Should collapsed/expanded state **per category** persist across
  sessions too, or reset each visit? (Issue only specifies the overall
  card/list toggle persists; defaulting to session-only expand state
  unless told otherwise.)
- Should the list view keep the existing paginated "N per page" behavior
  (via `useDataTable`) or rely on per-category collapse as the volume
  control, given challenges are now grouped rather than flat? (Plan
  recommends collapse-as-volume-control for v1, no separate pagination
  inside a category — open to reconsideration.)
- Is a plain emoji padlock (matching current card/dialog convention)
  acceptable in the list view long-term, or should this be the moment to
  introduce a proper icon set — out of scope for this issue either way,
  but worth flagging since it'd be a larger, unrelated dependency change.
