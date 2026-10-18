import { afterEach, describe, expect, it, vi } from "vitest";

import { scoreboardApi } from "@/lib/api";

// `live` reaches the server as ?live=true, beside the bracket filter (#501).

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch() {
  const fetchMock = vi.fn(
    async () => new Response(JSON.stringify({}), { status: 200 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return () => String((fetchMock.mock.calls.at(-1) as unknown[] | undefined)?.[0]);
}

describe("scoreboardApi", () => {
  it("asks for the live board only when told to", async () => {
    const lastUrl = stubFetch();
    await scoreboardApi.get("c1");
    expect(lastUrl()).toMatch(/\/api\/competitions\/c1\/scoreboard$/);
    await scoreboardApi.get("c1", null, true);
    expect(lastUrl()).toMatch(/\/scoreboard\?live=true$/);
  });

  it("combines the bracket and live on the timeline", async () => {
    const lastUrl = stubFetch();
    await scoreboardApi.timeline("c1", "Students & staff", true);
    expect(lastUrl()).toMatch(
      /\/scoreboard\/timeline\?bracket=Students\+%26\+staff&live=true$/,
    );
    await scoreboardApi.timeline("c1", null);
    expect(lastUrl()).toMatch(/\/scoreboard\/timeline$/);
  });
});
