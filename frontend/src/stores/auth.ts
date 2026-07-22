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

interface AuthState {
  accessToken: string | null;
  user: User | null;
  status: AuthStatus;
  activeCompetitionId: string | null;
  paletteOverride: string | null;
  setSession: (accessToken: string, user: User) => void;
  clearSession: () => void;
  setActiveCompetition: (competitionId: string | null) => void;
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
  clearSession: () =>
    set({ accessToken: null, user: null, status: "anonymous" }),
  setActiveCompetition: (competitionId) =>
    set({ activeCompetitionId: competitionId }),
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
