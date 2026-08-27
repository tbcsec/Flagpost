import { beforeEach, describe, expect, it } from "vitest";

import { pickActiveCompetitionId } from "@/lib/competition-selection";
import { useAuthStore } from "@/stores/auth";
import type { User } from "@/lib/types";

const user: User = {
  id: "u-1",
  email: "a@example.com",
  display_name: "Ada",
  created_at: new Date().toISOString(),
  email_verified_at: null,
  avatar_updated_at: null,
  username_change_allowed_at: null,
};

beforeEach(() => {
  window.localStorage.clear();
  useAuthStore.setState({
    accessToken: null,
    user: null,
    status: "loading",
    activeCompetitionId: null,
  });
});

const ACTIVE_COMPETITION_KEY = "fp:active-competition";

describe("auth store", () => {
  it("setSession moves to authenticated and stores token + user", () => {
    useAuthStore.getState().setSession("token-abc", user);
    const state = useAuthStore.getState();
    expect(state.status).toBe("authenticated");
    expect(state.accessToken).toBe("token-abc");
    expect(state.user?.email).toBe("a@example.com");
  });

  it("clearSession moves to anonymous and drops credentials", () => {
    useAuthStore.getState().setSession("token-abc", user);
    useAuthStore.getState().clearSession();
    const state = useAuthStore.getState();
    expect(state.status).toBe("anonymous");
    expect(state.accessToken).toBeNull();
    expect(state.user).toBeNull();
  });
});

// The active-competition selection must survive a reload (#316): setActiveCompetition
// write-throughs to localStorage, hydrateActiveCompetition restores it, and logout
// forgets it so the next user on this browser starts from their own default.
describe("active competition persistence", () => {
  it("setActiveCompetition write-throughs to localStorage", () => {
    useAuthStore.getState().setActiveCompetition("comp-1");
    expect(useAuthStore.getState().activeCompetitionId).toBe("comp-1");
    expect(window.localStorage.getItem(ACTIVE_COMPETITION_KEY)).toBe("comp-1");
  });

  it("setActiveCompetition(null) clears the persisted value", () => {
    useAuthStore.getState().setActiveCompetition("comp-1");
    useAuthStore.getState().setActiveCompetition(null);
    expect(useAuthStore.getState().activeCompetitionId).toBeNull();
    expect(window.localStorage.getItem(ACTIVE_COMPETITION_KEY)).toBeNull();
  });

  it("hydrateActiveCompetition restores a saved selection (the reload path)", () => {
    window.localStorage.setItem(ACTIVE_COMPETITION_KEY, "comp-7");
    // Simulate a fresh load: store starts null, hydrate pulls the saved id back.
    expect(useAuthStore.getState().activeCompetitionId).toBeNull();
    useAuthStore.getState().hydrateActiveCompetition();
    expect(useAuthStore.getState().activeCompetitionId).toBe("comp-7");
  });

  it("hydrateActiveCompetition is a no-op when nothing is stored", () => {
    useAuthStore.getState().hydrateActiveCompetition();
    expect(useAuthStore.getState().activeCompetitionId).toBeNull();
  });

  it("clearSession forgets the persisted competition (logout handoff)", () => {
    useAuthStore.getState().setActiveCompetition("comp-1");
    useAuthStore.getState().clearSession();
    expect(useAuthStore.getState().activeCompetitionId).toBeNull();
    expect(window.localStorage.getItem(ACTIVE_COMPETITION_KEY)).toBeNull();
  });

  it("hydrate leaves an already-set selection intact when nothing is stored", () => {
    // Guards the `if (saved)` conditional: an unconditional set() would clobber
    // a live selection with null. (Unreachable at runtime today, but the
    // conditional is load-bearing if hydrate is ever called after a selection.)
    useAuthStore.setState({ activeCompetitionId: "already-picked" });
    useAuthStore.getState().hydrateActiveCompetition();
    expect(useAuthStore.getState().activeCompetitionId).toBe("already-picked");
  });
});

// The integration seam the shell relies on (app-shell default-selection effect):
// restore the persisted id, reconcile it against the competitions the user can
// see via pickActiveCompetitionId, and write the correction back — id AND
// storage. This end-to-end path is what actually fixes #316; the unit tests
// above only cover its pieces.
describe("restore + validate + write-back (the #316 seam)", () => {
  const visible = ["a", "b", "c"];

  function reconcile() {
    const state = useAuthStore.getState();
    const next = pickActiveCompetitionId(state.activeCompetitionId, visible);
    if (next && next !== state.activeCompetitionId) state.setActiveCompetition(next);
  }

  it("keeps a still-valid restored id and does not rewrite storage", () => {
    window.localStorage.setItem(ACTIVE_COMPETITION_KEY, "b");
    useAuthStore.getState().hydrateActiveCompetition();
    reconcile();
    expect(useAuthStore.getState().activeCompetitionId).toBe("b");
    expect(window.localStorage.getItem(ACTIVE_COMPETITION_KEY)).toBe("b");
  });

  it("corrects a stale restored id to the first competition AND re-persists it", () => {
    // A reload where localStorage held a since-deleted / no-longer-visible id.
    window.localStorage.setItem(ACTIVE_COMPETITION_KEY, "deleted-comp");
    useAuthStore.getState().hydrateActiveCompetition();
    expect(useAuthStore.getState().activeCompetitionId).toBe("deleted-comp");
    reconcile();
    expect(useAuthStore.getState().activeCompetitionId).toBe("a");
    // The stale id must not survive in storage, or the next reload repeats it.
    expect(window.localStorage.getItem(ACTIVE_COMPETITION_KEY)).toBe("a");
  });

  it("seeds the first competition on a fresh load with nothing stored", () => {
    useAuthStore.getState().hydrateActiveCompetition(); // no-op, nothing stored
    reconcile();
    expect(useAuthStore.getState().activeCompetitionId).toBe("a");
    expect(window.localStorage.getItem(ACTIVE_COMPETITION_KEY)).toBe("a");
  });
});
