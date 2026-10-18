import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useFreezeScoreboard, useScoreboard } from "@/lib/hooks/use-scoreboard";
import type { Scoreboard } from "@/lib/types";

// The staff live view during a freeze (#501): its own room and cache entry, so
// the shared (competitor) board and the live one never overwrite each other.

const get = vi.fn();
const freeze = vi.fn();
const unfreeze = vi.fn();
vi.mock("@/lib/api", () => ({
  scoreboardApi: {
    get: (...args: unknown[]) => get(...args),
    timeline: vi.fn(),
    freeze: (cid: string) => freeze(cid),
    unfreeze: (cid: string) => unfreeze(cid),
  },
}));

type Handlers = { onMessage: (data: unknown) => void };
const sockets: { room: string; id: string; handlers: Handlers }[] = [];
vi.mock("@/lib/ws", () => ({
  openRoomSocket: (room: string, id: string, handlers: Handlers) => {
    sockets.push({ room, id, handlers });
    return { close: vi.fn() };
  },
}));
vi.mock("@/stores/auth", () => ({
  useAuthStore: (select: (s: { status: string }) => unknown) =>
    select({ status: "authenticated" }),
}));

function board(overrides: Partial<Scoreboard> = {}): Scoreboard {
  return {
    competition_id: "c1",
    mode: "team",
    entries: [],
    frozen: false,
    frozen_at: null,
    live: false,
    brackets: [],
    ...overrides,
  };
}

const SHARED = ["scoreboard", "c1", "shared"];
const LIVE = ["scoreboard", "c1", "live"];

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  get.mockReset();
  freeze.mockReset();
  unfreeze.mockReset();
  sockets.length = 0;
});

describe("useScoreboard", () => {
  it("reads the shared board from the shared room by default", async () => {
    get.mockResolvedValue(board({ frozen: true }));
    const { result } = renderHook(() => useScoreboard("c1"), { wrapper });
    await waitFor(() => expect(result.current.data?.frozen).toBe(true));
    expect(get).toHaveBeenCalledWith("c1", null, false);
    expect(sockets.map((s) => s.room)).toEqual(["scoreboard"]);
  });

  it("reads the live board from the staff room when asked", async () => {
    get.mockResolvedValue(board({ live: true }));
    const { result } = renderHook(() => useScoreboard("c1", { live: true }), { wrapper });
    await waitFor(() => expect(result.current.data?.live).toBe(true));
    expect(get).toHaveBeenCalledWith("c1", null, true);
    expect(sockets.map((s) => s.room)).toEqual(["scoreboard_live"]);
  });

  it("a live frame updates the live board, drops the shared one and refreshes the chart", async () => {
    get.mockResolvedValue(board({ live: true }));
    client.setQueryData(SHARED, board({ frozen: true }));
    const invalidate = vi.spyOn(client, "invalidateQueries");
    renderHook(() => useScoreboard("c1", { live: true }), { wrapper });
    await waitFor(() => expect(sockets).toHaveLength(1));

    act(() =>
      sockets[0].handlers.onMessage({
        type: "scoreboard",
        ...board({
          live: true,
          entries: [
            { rank: 1, subject_id: "t1", name: "A", points: 300, last_solve_at: null, bracket: null },
          ],
        }),
      }),
    );
    expect(client.getQueryData<Scoreboard>(LIVE)?.entries[0].points).toBe(300);
    expect(client.getQueryData(SHARED)).toBeUndefined();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["scoreboard-timeline", "c1"] });
  });

  it("an unfrozen frame leaves the chart to the activity room", async () => {
    get.mockResolvedValue(board());
    const invalidate = vi.spyOn(client, "invalidateQueries");
    renderHook(() => useScoreboard("c1"), { wrapper });
    await waitFor(() => expect(sockets).toHaveLength(1));
    act(() => sockets[0].handlers.onMessage({ type: "scoreboard", ...board() }));
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("keeps the current board on screen while the other view loads", async () => {
    get.mockResolvedValueOnce(board({ frozen: true }));
    const { result, rerender } = renderHook(
      ({ live }) => useScoreboard("c1", { live }),
      { wrapper, initialProps: { live: false } },
    );
    await waitFor(() => expect(result.current.data?.frozen).toBe(true));

    let resolveLive: (b: Scoreboard) => void = () => {};
    get.mockReturnValueOnce(new Promise<Scoreboard>((r) => (resolveLive = r)));
    rerender({ live: true });
    expect(result.current.data?.frozen).toBe(true);
    // The socket moves to the staff room with the view.
    expect(sockets.map((s) => s.room)).toEqual(["scoreboard", "scoreboard_live"]);

    await act(async () => resolveLive(board({ live: true })));
    await waitFor(() => expect(result.current.data?.live).toBe(true));
  });

  it("never shows live standings while the frozen view loads", async () => {
    get.mockResolvedValueOnce(board({ live: true }));
    const { result, rerender } = renderHook(
      ({ live }) => useScoreboard("c1", { live }),
      { wrapper, initialProps: { live: true } },
    );
    await waitFor(() => expect(result.current.data?.live).toBe(true));
    get.mockReturnValueOnce(new Promise(() => {}));
    rerender({ live: false });
    expect(result.current.data).toBeUndefined();
  });

  it("doesn't carry a board across competitions", async () => {
    get.mockResolvedValueOnce(board({ frozen: true }));
    const { result, rerender } = renderHook(({ cid }) => useScoreboard(cid), {
      wrapper,
      initialProps: { cid: "c1" },
    });
    await waitFor(() => expect(result.current.data?.frozen).toBe(true));
    get.mockReturnValueOnce(new Promise(() => {}));
    rerender({ cid: "c2" });
    expect(result.current.data).toBeUndefined();
  });
});

describe("useFreezeScoreboard", () => {
  it("a freeze stores the live board and refetches the shared one", async () => {
    freeze.mockResolvedValue(board({ live: true }));
    client.setQueryData(SHARED, board());
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useFreezeScoreboard("c1"), { wrapper });
    await act(async () => result.current.mutateAsync(true));
    expect(client.getQueryData<Scoreboard>(LIVE)?.live).toBe(true);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: SHARED });
  });

  it("a freeze stays pending until the frozen board has loaded", async () => {
    freeze.mockResolvedValue(board({ live: true }));
    // The shared view is on screen with the unfrozen board, so its query is
    // active and the freeze refetches it.
    get.mockResolvedValueOnce(board());
    const shared = renderHook(() => useScoreboard("c1"), { wrapper });
    await waitFor(() => expect(shared.result.current.data).toBeDefined());
    let resolveShared: (b: Scoreboard) => void = () => {};
    get.mockReturnValueOnce(new Promise<Scoreboard>((r) => (resolveShared = r)));
    const { result } = renderHook(() => useFreezeScoreboard("c1"), { wrapper });
    act(() => result.current.mutate(true));
    await waitFor(() => expect(freeze).toHaveBeenCalled());
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(result.current.isPending).toBe(true);
    await act(async () => resolveShared(board({ frozen: true })));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("an unfreeze gives both views the same board", async () => {
    unfreeze.mockResolvedValue(board());
    const { result } = renderHook(() => useFreezeScoreboard("c1"), { wrapper });
    await act(async () => result.current.mutateAsync(false));
    expect(client.getQueryData(LIVE)).toEqual(board());
    expect(client.getQueryData(SHARED)).toEqual(board());
  });
});
