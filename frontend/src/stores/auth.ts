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

// Palette is a UI preference (client state, §2). The app is dark-first; the
// topbar toggle flips this and the shell mirrors it onto <html data-palette>.
type Palette = "dark" | "light";

interface AuthState {
  accessToken: string | null;
  user: User | null;
  status: AuthStatus;
  activeCompetitionId: string | null;
  palette: Palette;
  setSession: (accessToken: string, user: User) => void;
  clearSession: () => void;
  setActiveCompetition: (competitionId: string | null) => void;
  togglePalette: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  user: null,
  status: "loading",
  activeCompetitionId: null,
  palette: "dark",
  setSession: (accessToken, user) =>
    set({ accessToken, user, status: "authenticated" }),
  clearSession: () =>
    set({ accessToken: null, user: null, status: "anonymous" }),
  setActiveCompetition: (competitionId) =>
    set({ activeCompetitionId: competitionId }),
  togglePalette: () =>
    set((s) => ({ palette: s.palette === "dark" ? "light" : "dark" })),
}));
