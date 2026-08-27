// Which competition should be active, given the current selection and the
// competitions the user can actually see. Pure so the shell's default-selection
// effect stays trivial and the staleness rule (#316) is unit-tested directly.
//
// The rule: keep the current selection when it's still visible; otherwise fall
// back to the first competition; return null only when there are none. A
// persisted id (restored from localStorage on load) is just a "current"
// selection here — so a stale or foreign id transparently falls back to the
// first instead of leaving the switcher pointing at a competition the user
// can't load.
export function pickActiveCompetitionId(
  currentId: string | null | undefined,
  visibleIds: readonly string[],
): string | null {
  if (currentId && visibleIds.includes(currentId)) return currentId;
  return visibleIds[0] ?? null;
}
