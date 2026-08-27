import { create } from "zustand";

import type { User } from "@/lib/types";

// Client/UI/session state only (ARCHITECTURE.md §2): the access token and the
// identity it resolves to, plus the active-competition context. Server data
// (competitions, etc.) never lives here — that goes through TanStack Query
// hooks (§8).
//
// The access token is held in memory only — never localStorage — so injected
// JS can't read it (§7.7). The durable credential is the httpOnly refresh
// cookie; on a fresh load the token is restored by calling /auth/refresh.

type AuthStatus = "loading" | "authenticated" | "anonymous";

// The palette is a per-user UI preference (client state, §2) that overrides the
// site-wide default palette an administrator sets (§9). `null` = follow the site
// default. The topbar palette menu writes this; the ThemeApplier resolves
// override ?? site-default and mirrors it onto <html data-palette>.
const PALETTE_OVERRIDE_KEY = "fp:palette-override";

// The active-competition selection is client/UI context (§2), persisted so a
// page reload keeps the competition the user was working in instead of snapping
// back to the first one (#316). It is a plain id, not a credential — the shell
// re-validates it against the competitions the current user can actually see
// before trusting it, and it's cleared on logout so a different user on the same
// browser doesn't inherit it. `hydrateActiveCompetition` restores it on load.
const ACTIVE_COMPETITION_KEY = "fp:active-competition";

interface AuthState {
  accessToken: string | null;
  user: User | null;
  status: AuthStatus;
  activeCompetitionId: string | null;
  paletteOverride: string | null;
  setSession: (accessToken: string, user: User) => void;
  /** Refresh just the cached user (e.g. after a self-service email change),
   *  leaving the access token untouched — setSession would demand one. */
  setUser: (user: User) => void;
  clearSession: () => void;
  setActiveCompetition: (competitionId: string | null) => void;
  /** Restore the persisted active competition on load. SSR-safe; a no-op when
   *  nothing is stored. The shell validates the restored id before trusting it. */
  hydrateActiveCompetition: () => void;
  setPaletteOverride: (palette: string | null) => void;
  hydratePaletteOverride: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  user: null,
  status: "loading",
  activeCompetitionId: null,
  // SSR-safe default; the saved override is applied by hydratePaletteOverride.
  paletteOverride: null,
  setSession: (accessToken, user) =>
    set({ accessToken, user, status: "authenticated" }),
  setUser: (user) => set({ user }),
  clearSession: () => {
    // Logout (or a failed refresh) forgets the persisted competition so the next
    // user on this browser starts from their own default, not the last one (#316).
    try {
      window.localStorage.removeItem(ACTIVE_COMPETITION_KEY);
    } catch {
      /* SSR / private mode — non-fatal */
    }
    set({
      accessToken: null,
      user: null,
      status: "anonymous",
      activeCompetitionId: null,
    });
  },
  setActiveCompetition: (competitionId) => {
    try {
      if (competitionId)
        window.localStorage.setItem(ACTIVE_COMPETITION_KEY, competitionId);
      else window.localStorage.removeItem(ACTIVE_COMPETITION_KEY);
    } catch {
      /* SSR / private mode — the choice just won't survive a reload */
    }
    set({ activeCompetitionId: competitionId });
  },
  hydrateActiveCompetition: () => {
    try {
      const saved = window.localStorage.getItem(ACTIVE_COMPETITION_KEY);
      if (saved) set({ activeCompetitionId: saved });
    } catch {
      /* no-op */
    }
  },
  setPaletteOverride: (palette) => {
    try {
      if (palette) window.localStorage.setItem(PALETTE_OVERRIDE_KEY, palette);
      else window.localStorage.removeItem(PALETTE_OVERRIDE_KEY);
    } catch {
      /* private mode / SSR — non-fatal, the choice just won't persist */
    }
    set({ paletteOverride: palette });
  },
  hydratePaletteOverride: () => {
    try {
      const saved = window.localStorage.getItem(PALETTE_OVERRIDE_KEY);
      if (saved) set({ paletteOverride: saved });
    } catch {
      /* no-op */
    }
  },
}));
