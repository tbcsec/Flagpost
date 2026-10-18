import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useJoinByCode } from "@/lib/hooks/use-competitions";

// After a join (#478): the joined competition is listed and active at once — a
// private one isn't in the list until the refetch, and the switcher would
// otherwise move the selection away — and the join stays pending until
// permissions show the membership.

const joinByCode = vi.fn();
const list = vi.fn();
const permissions = vi.fn();
vi.mock("@/lib/api", () => ({
  competitionsApi: {
    joinByCode: (...a: unknown[]) => joinByCode(...a),
    list: () => list(),
  },
  authApi: { permissions: () => permissions() },
}));
const setActiveCompetition = vi.fn();
vi.mock("@/stores/auth", () => ({
  useAuthStore: (select: (s: { setActiveCompetition: typeof setActiveCompetition }) => unknown) =>
    select({ setActiveCompetition }),
}));

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  for (const f of [joinByCode, list, permissions, setActiveCompetition]) f.mockReset();
});

describe("joining", () => {
  it("lists and activates the joined competition, then waits for permissions", async () => {
    const PRIVATE = { id: "p", name: "Winter Invitational" };
    joinByCode.mockResolvedValue(PRIVATE);
    list.mockReturnValue(new Promise(() => {}));
    let resolvePermissions: (v: unknown) => void = () => {};
    permissions.mockReturnValue(new Promise((r) => (resolvePermissions = r)));
    client.setQueryData(["competitions"], [{ id: "a", name: "Autumn CTF" }]);
    // Permissions are observed, as in the shell, so the invalidation refetches.
    client.setQueryData(["permissions"], { global: [], by_competition: {} });
    renderHook(
      () => useQuery({ queryKey: ["permissions"], queryFn: () => permissions(), staleTime: Infinity }),
      { wrapper },
    );

    const { result } = renderHook(() => useJoinByCode(), { wrapper });
    act(() => result.current.mutate({ inviteCode: "code" }));
    await waitFor(() => expect(setActiveCompetition).toHaveBeenCalledWith("p"));
    expect(client.getQueryData<{ id: string }[]>(["competitions"])?.map((c) => c.id)).toEqual(["a", "p"]);
    expect(result.current.isPending).toBe(true);

    await act(async () => resolvePermissions({ global: [], by_competition: { p: [] } }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});
