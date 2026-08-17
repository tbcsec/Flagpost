import { describe, expect, it } from "vitest";

import { apiTokenStatus } from "@/lib/api-token-status";

describe("apiTokenStatus", () => {
  it("is Revoked whenever revoked_at is set, even if not yet expired", () => {
    const future = new Date(Date.now() + 86_400_000).toISOString();
    expect(apiTokenStatus({ expires_at: future, revoked_at: new Date().toISOString() })).toEqual({
      key: "revoked",
      label: "Revoked",
      variant: "muted",
    });
  });

  it("is Expired once expires_at is in the past and it hasn't been revoked", () => {
    const past = new Date(Date.now() - 86_400_000).toISOString();
    expect(apiTokenStatus({ expires_at: past, revoked_at: null })).toEqual({
      key: "expired",
      label: "Expired",
      variant: "destructive",
    });
  });

  it("is Active when neither revoked nor expired", () => {
    const future = new Date(Date.now() + 86_400_000).toISOString();
    expect(apiTokenStatus({ expires_at: future, revoked_at: null })).toEqual({
      key: "active",
      label: "Active",
      variant: "success",
    });
  });
});
