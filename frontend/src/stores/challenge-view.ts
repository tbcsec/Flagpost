import { create } from "zustand";

// Per-device UI preferences for the challenges browse page (#55): which layout
// the player wants (the default card grid vs. the grouped list) and, in list
// view, which category sections are expanded.
//
// Client/UI state only (ARCHITECTURE.md §2) — a *local-device* preference, not
// synced to the backend profile. Both persist across sessions in localStorage,
// hand-rolled exactly like auth.ts's `paletteOverride`: no zustand `persist`
// middleware, SSR-safe defaults (so the store is identical on server and first
// client render), hydrated once from a mount effect on the page. Writes are
// wrapped in try/catch so private-mode / SSR degrade to "the choice just won't
// persist" rather than throwing.

export type ChallengeViewMode = "card" | "list";

const VIEW_MODE_KEY = "fp:challenges-view";
const EXPANDED_KEY = "fp:challenges-expanded";

interface ChallengeViewState {
  viewMode: ChallengeViewMode;
  // Category ids whose list section is expanded. Absent ⇒ collapsed, so a fresh
  // visitor sees every category collapsed (the confirmed default). Category ids
  // are globally-unique UUIDs, so one flat set is safe across competitions —
  // an id from another competition simply never matches a rendered section.
  expanded: string[];
  setViewMode: (mode: ChallengeViewMode) => void;
  toggleCategory: (id: string) => void;
  hydrate: () => void;
}

function persist(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* private mode / SSR — non-fatal, the choice just won't persist */
  }
}

export const useChallengeViewStore = create<ChallengeViewState>((set, get) => ({
  // SSR-safe defaults; the saved values are applied by hydrate().
  viewMode: "card",
  expanded: [],
  setViewMode: (mode) => {
    persist(VIEW_MODE_KEY, mode);
    set({ viewMode: mode });
  },
  toggleCategory: (id) => {
    const current = get().expanded;
    const expanded = current.includes(id)
      ? current.filter((x) => x !== id)
      : [...current, id];
    persist(EXPANDED_KEY, JSON.stringify(expanded));
    set({ expanded });
  },
  hydrate: () => {
    try {
      const next: Partial<ChallengeViewState> = {};
      const savedMode = window.localStorage.getItem(VIEW_MODE_KEY);
      if (savedMode === "card" || savedMode === "list") next.viewMode = savedMode;
      const savedExpanded = window.localStorage.getItem(EXPANDED_KEY);
      if (savedExpanded) {
        const parsed: unknown = JSON.parse(savedExpanded);
        if (Array.isArray(parsed)) {
          next.expanded = parsed.filter((x): x is string => typeof x === "string");
        }
      }
      if (Object.keys(next).length > 0) set(next);
    } catch {
      /* absent or corrupt storage — fall back to the SSR-safe defaults */
    }
  },
}));
