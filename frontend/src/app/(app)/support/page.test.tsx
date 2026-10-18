import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SupportPage from "@/app/(app)/support/page";
import type { Ticket } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";

// Staff work the queue beside the open ticket, which lives in the URL (#503);
// a competitor keeps their simple list.

let isStaff = true;
let search = "";
const push = vi.fn();
const replace = vi.fn();
const mounts = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => "/support",
  useSearchParams: () => new URLSearchParams(search),
}));
vi.mock("@/lib/hooks/use-competitions", () => ({
  useActiveCompetition: () => ({ competitionId: "c1", data: { id: "c1", name: "Spring CTF" } }),
}));
vi.mock("@/lib/hooks/use-permissions", () => ({
  useAccess: () => ({ has: (p: string) => isStaff && p === "ticket_assign" }),
}));
const TICKET: Ticket = {
  id: "t1",
  subject: "Instance won't start",
  kind: "support",
  status: "open",
  challenge_id: null,
  challenge_title: null,
  opener_name: "mei",
  team_name: null,
  assignee_name: null,
  assignee_user_id: null,
  message_count: 1,
  created_at: "2026-10-18T09:00:00Z",
  last_activity_at: "2026-10-18T09:00:00Z",
  awaiting_staff: true,
};
vi.mock("@/lib/hooks/use-tickets", () => ({
  useTickets: () => ({ data: [TICKET], isLoading: false }),
  useSupportQueueLive: vi.fn(),
}));
vi.mock("@/components/support/staff-ticket-view", async () => {
  const { useState } = await import("react");
  return {
    StaffTicketView: ({ ticketId }: { ticketId: string }) => {
      // Runs once per mount: a fresh view per ticket keeps drafts from
      // following you (a prop change alone wouldn't re-run it).
      useState(() => mounts(ticketId));
      return <div>staff view {ticketId}</div>;
    },
  };
});
vi.mock("@/components/support/ticket-thread", () => ({
  TicketThread: ({ ticketId }: { ticketId: string }) => <div>thread {ticketId}</div>,
}));
vi.mock("@/components/support/new-ticket-dialog", () => ({
  NewTicketDialog: () => <button type="button">New ticket</button>,
}));
vi.mock("@/stores/auth", () => ({
  useAuthStore: (select: (s: { user: { id: string } }) => unknown) => select({ user: { id: "judge-1" } }),
}));

beforeEach(() => {
  isStaff = true;
  search = "";
  push.mockReset();
  replace.mockReset();
  mounts.mockReset();
});

describe("Support for staff", () => {
  it("shows the queue, a summary and a prompt to pick a ticket", () => {
    renderWithIntl(<SupportPage />);
    expect(screen.getByText("Spring CTF · 1 open · 1 waiting on staff")).toBeInTheDocument();
    expect(screen.getByText("Pick a ticket")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Instance won't start"));
    expect(push).toHaveBeenCalledWith("/support?ticket=t1", { scroll: false });
  });

  it("opens the ticket named in the URL, with a way back on a phone", () => {
    search = "ticket=t1";
    renderWithIntl(<SupportPage />);
    expect(screen.getByText("staff view t1")).toBeInTheDocument();
    // On a phone the queue steps aside while a ticket is open.
    expect(screen.getByText("Instance won't start").closest("[class*='hidden']")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Back to queue/ }));
    expect(push).toHaveBeenCalledWith("/support", { scroll: false });
  });

  it("moves between tickets without piling up history, keeping other parameters", () => {
    search = "foo=1&ticket=t0";
    renderWithIntl(<SupportPage />);
    fireEvent.click(screen.getByText("Instance won't start"));
    expect(replace).toHaveBeenCalledWith("/support?foo=1&ticket=t1", { scroll: false });
    expect(push).not.toHaveBeenCalled();
  });

  it("mounts a fresh ticket view for each ticket", () => {
    search = "ticket=t1";
    const { rerender } = renderWithIntl(<SupportPage />);
    search = "ticket=t2";
    rerender(<SupportPage />);
    expect(mounts.mock.calls.map((c) => c[0])).toEqual(["t1", "t2"]);
  });
});

describe("Support for a competitor", () => {
  it("keeps the simple list of their own tickets", () => {
    isStaff = false;
    renderWithIntl(<SupportPage />);
    expect(screen.getByText("Spring CTF · your tickets")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "New ticket" }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("group", { name: "Quick filters" })).toBeNull();
    expect(screen.getByText(/1 message/)).toBeInTheDocument();
  });

  it("opens the ticket a notification links to, and clears it on close (#508)", () => {
    isStaff = false;
    search = "ticket=t1";
    renderWithIntl(<SupportPage />);
    expect(screen.getByText("thread t1")).toBeInTheDocument();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(push).toHaveBeenCalledWith("/support", { scroll: false });
  });

  it("puts a ticket it opens into the URL", () => {
    isStaff = false;
    renderWithIntl(<SupportPage />);
    fireEvent.click(screen.getByText("Instance won't start"));
    expect(push).toHaveBeenCalledWith("/support?ticket=t1", { scroll: false });
  });
});
