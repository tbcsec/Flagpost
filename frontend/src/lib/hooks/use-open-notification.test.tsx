import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useOpenNotification } from "@/lib/hooks/use-notifications";
import type { AppNotification } from "@/lib/types";

// Activating a notification in the bell (#508): mark it read, and switch to its
// competition so its Support link opens the right ticket.

const markRead = vi.fn();
vi.mock("@/lib/api", () => ({
  notificationsApi: { markRead: (id: string) => markRead(id) },
}));
const setActiveCompetition = vi.fn();
let activeCompetitionId: string | null = "c1";
vi.mock("@/stores/auth", () => ({
  useAuthStore: (
    select: (s: { activeCompetitionId: string | null; setActiveCompetition: typeof setActiveCompetition }) => unknown,
  ) => select({ activeCompetitionId, setActiveCompetition }),
}));

const notification = (over: Partial<AppNotification> = {}): AppNotification => ({
  id: "n1",
  type: "ticket.created",
  title: "New support ticket",
  body: null,
  link: "/support?ticket=t1",
  competition_id: "c1",
  read: false,
  created_at: "2026-10-18T10:00:00Z",
  ...over,
});

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  markRead.mockReset().mockResolvedValue(undefined);
  setActiveCompetition.mockReset();
  activeCompetitionId = "c1";
});

describe("useOpenNotification", () => {
  it("marks an unread notification read and stays on its competition", async () => {
    const { result } = renderHook(() => useOpenNotification(), { wrapper });
    act(() => result.current(notification()));
    // The mutation runs on the next tick.
    await waitFor(() => expect(markRead).toHaveBeenCalledWith("n1"));
    expect(setActiveCompetition).not.toHaveBeenCalled();
  });

  it("switches to another competition's ticket first, leaving a read one alone", async () => {
    const { result } = renderHook(() => useOpenNotification(), { wrapper });
    act(() => result.current(notification({ competition_id: "c2", read: true })));
    expect(setActiveCompetition).toHaveBeenCalledWith("c2");
    // Give a stray mutation the tick it would need before asserting none ran.
    await act(async () => {});
    expect(markRead).not.toHaveBeenCalled();
  });
});
