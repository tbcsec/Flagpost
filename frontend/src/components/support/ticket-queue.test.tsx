import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { filterQueue, TicketQueue } from "@/components/support/ticket-queue";
import type { Ticket } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";

// The staff queue (#503): status tabs, one quick filter, most recent first.

function ticket(id: string, over: Partial<Ticket> = {}): Ticket {
  return {
    id,
    subject: `Ticket ${id}`,
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
    awaiting_staff: false,
    ...over,
  };
}

const TICKETS = [
  ticket("a", { awaiting_staff: true, last_activity_at: "2026-10-18T10:00:00Z" }),
  ticket("b", { assignee_user_id: "me", assignee_name: "me", last_activity_at: "2026-10-18T11:00:00Z" }),
  ticket("c", { status: "resolved", assignee_user_id: "me", assignee_name: "me" }),
  ticket("d", { assignee_user_id: "other", assignee_name: "ana", last_activity_at: "2026-10-18T12:00:00Z" }),
];

describe("filterQueue", () => {
  const ids = (list: Ticket[]) => list.map((t) => t.id);

  it("shows open work, most recently active first", () => {
    expect(ids(filterQueue(TICKETS, { status: "open", focus: null, userId: "me" }))).toEqual(["d", "b", "a"]);
    expect(ids(filterQueue(TICKETS, { status: "resolved", focus: null, userId: "me" }))).toEqual(["c"]);
    expect(ids(filterQueue(TICKETS, { status: "all", focus: null, userId: "me" }))).toHaveLength(4);
  });

  it("narrows to waiting, mine or unassigned", () => {
    expect(ids(filterQueue(TICKETS, { status: "open", focus: "waiting", userId: "me" }))).toEqual(["a"]);
    expect(ids(filterQueue(TICKETS, { status: "all", focus: "mine", userId: "me" }))).toEqual(["b", "c"]);
    expect(ids(filterQueue(TICKETS, { status: "all", focus: "unassigned", userId: "me" }))).toEqual(["a"]);
    // A resolved ticket nobody took isn't waiting for an owner.
    const withResolved = [...TICKETS, ticket("r", { status: "resolved" })];
    expect(ids(filterQueue(withResolved, { status: "all", focus: "unassigned", userId: "me" }))).toEqual(["a"]);
    // No user, nothing is "mine".
    expect(filterQueue(TICKETS, { status: "all", focus: "mine" })).toEqual([]);
  });
});

describe("TicketQueue", () => {
  const queue = (onSelect = vi.fn(), selectedId: string | null = null) =>
    renderWithIntl(
      <TicketQueue tickets={TICKETS} selectedId={selectedId} onSelect={onSelect} userId="me" />,
    );

  it("counts each quick filter and applies one at a time", () => {
    queue();
    const filters = screen.getByRole("group", { name: "Quick filters" });
    const waiting = within(filters).getByRole("button", { name: /Waiting on staff/ });
    expect(waiting).toHaveTextContent("1");
    expect(within(filters).getByRole("button", { name: /Mine/ })).toHaveTextContent("1");
    expect(within(filters).getByRole("button", { name: /Unassigned/ })).toHaveTextContent("1");

    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    fireEvent.click(waiting);
    expect(waiting).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText("Ticket a")).toBeInTheDocument();
    fireEvent.click(waiting);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });

  it("switches status tabs and selects a ticket", () => {
    const onSelect = vi.fn();
    queue(onSelect, "b");
    fireEvent.click(screen.getByRole("tab", { name: "resolved" }));
    expect(screen.getByText("Ticket c")).toBeInTheDocument();
    expect(screen.queryByText("Ticket a")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "open" }));
    expect(screen.getByText("Ticket b").closest("button")).toHaveAttribute("aria-current", "true");
    fireEvent.click(screen.getByText("Ticket d"));
    expect(onSelect).toHaveBeenCalledWith("d");
  });

  it("shows who has each ticket and flags the waiting one", () => {
    queue();
    const row = screen.getByText("Ticket a").closest("button")!;
    expect(within(row).getByRole("img", { name: "Waiting on staff" })).toBeInTheDocument();
    expect(row).toHaveTextContent("Unassigned");
    expect(screen.getByText("Ticket d").closest("button")).toHaveTextContent("ana");
  });

  it("counts only open tickets as unassigned", () => {
    renderWithIntl(
      <TicketQueue
        tickets={[...TICKETS, ticket("e", { status: "resolved" })]}
        selectedId={null}
        onSelect={vi.fn()}
        userId="me"
      />,
    );
    const filters = screen.getByRole("group", { name: "Quick filters" });
    expect(within(filters).getByRole("button", { name: /Unassigned/ })).toHaveTextContent("1");
  });

  it("goes back to the first page when a filter changes", () => {
    // 22 open tickets, 12 of them waiting: both lists span two pages of ten.
    const many = Array.from({ length: 22 }, (_, i) =>
      ticket(`m${i}`, { awaiting_staff: i < 12, last_activity_at: `2026-10-18T10:${String(i).padStart(2, "0")}:00Z` }),
    );
    renderWithIntl(<TicketQueue tickets={many} selectedId={null} onSelect={vi.fn()} userId="me" />);
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(screen.getAllByRole("listitem")).toHaveLength(10);
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    fireEvent.click(within(screen.getByRole("group", { name: "Quick filters" })).getByRole("button", { name: /Waiting/ }));
    expect(screen.getAllByRole("listitem")).toHaveLength(10);
  });
});
