import { afterEach, describe, expect, it, vi } from "vitest";

import { authApi } from "@/lib/api";

// A refresh token rotates once (GHSA-vv68), so tabs restoring a session at the
// same moment must take turns rather than race on the same token.

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const session = {
  access_token: "a",
  user: { id: "u", display_name: "u", email: null },
};

describe("session refresh", () => {
  it("takes the cross-tab lock around the refresh request", async () => {
    const order: string[] = [];
    const fetchMock = vi.fn(async () => {
      order.push("fetch");
      return new Response(JSON.stringify(session), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const request = vi.fn(async (name: string, run: () => Promise<boolean>) => {
      order.push(`lock:${name}`);
      const result = await run();
      order.push("unlock");
      return result;
    });
    vi.stubGlobal("navigator", { ...navigator, locks: { request } });

    await expect(authApi.restore()).resolves.toBe(true);
    expect(order).toEqual(["lock:flagpost-auth-refresh", "fetch", "unlock"]);
  });

  it("refreshes without the lock when the browser refuses it", async () => {
    const request = vi.fn(async () => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.stubGlobal("navigator", { ...navigator, locks: { request } });
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(session), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(authApi.restore()).resolves.toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("bounds the refresh request", async () => {
    vi.stubGlobal("navigator", { ...navigator, locks: undefined });
    const fetchMock = vi.fn(
      async (_url: string, init?: RequestInit) =>
        new Response(JSON.stringify(session), { status: init?.signal ? 200 : 500 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await expect(authApi.restore()).resolves.toBe(true);
  });

  it("still refreshes where Web Locks are unavailable", async () => {
    vi.stubGlobal("navigator", { ...navigator, locks: undefined });
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(session), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(authApi.restore()).resolves.toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
