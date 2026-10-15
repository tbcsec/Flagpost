import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useHasProgrammingProblems } from "@/lib/hooks/use-judge";

// The sidebar's Judging entry (#450): shown only once the competition has a
// programming problem.

const queue = vi.fn();
vi.mock("@/lib/api", () => ({
  juryApi: { queue: (cid: string) => queue(cid) },
  judgeAdminApi: {},
  judgeProblemApi: {},
  judgingsApi: {},
}));

const summary = (problems: number) => ({
  queued: 0,
  running: 0,
  site_queued: 0,
  site_running: 0,
  judge_enabled: true,
  problems,
});

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queue.mockReset();
});

describe("useHasProgrammingProblems", () => {
  it("is false for a flag-only competition and true once there's a problem", async () => {
    queue.mockResolvedValue(summary(0));
    const { result } = renderHook(() => useHasProgrammingProblems("c1", true), { wrapper });
    await waitFor(() => expect(result.current.data).toBe(false));

    // Anything that refreshes the challenge list refreshes this too.
    queue.mockResolvedValue(summary(2));
    await client.invalidateQueries({ queryKey: ["challenges", "c1"] });
    await waitFor(() => expect(result.current.data).toBe(true));
    expect(queue).toHaveBeenCalledWith("c1");
  });

  it("asks nothing for someone who can't see the console", () => {
    renderHook(() => useHasProgrammingProblems("c1", false), { wrapper });
    expect(queue).not.toHaveBeenCalled();
  });
});
