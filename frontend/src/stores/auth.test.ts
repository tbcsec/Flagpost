import { beforeEach, describe, expect, it } from "vitest";

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
  useAuthStore.setState({
    accessToken: null,
    user: null,
    status: "loading",
    activeCompetitionId: null,
  });
});

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
