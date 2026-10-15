import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import {
  ClarificationsLink,
  ProblemClarifications,
} from "@/components/challenges/problem-clarifications";
import type { Clarification, Ticket } from "@/lib/types";

// Questions about a problem and the judges' clarifications (#450).

let clarifications: Clarification[];
let tickets: Ticket[];
let grants: string[];
const createTicket = vi.fn();
const ticketsEnabled: boolean[] = [];

vi.mock("@/lib/hooks/use-announcements", () => ({
  useClarifications: () => ({ data: clarifications }),
}));
vi.mock("@/lib/hooks/use-tickets", () => ({
  useTickets: (_cid: string, _status: unknown, opts: { enabled: boolean }) => {
    ticketsEnabled.push(opts.enabled);
    return { data: tickets };
  },
  useCreateTicket: () => ({ mutate: createTicket, isPending: false, isError: false }),
}));
vi.mock("@/lib/hooks/use-permissions", () => ({
  useAccess: () => ({ has: (p: string) => grants.includes(p) }),
}));
vi.mock("@/components/support/ticket-thread", () => ({
  TicketThread: ({ ticketId, onAskAgain }: { ticketId: string; onAskAgain?: () => void }) => (
    <div>
      thread {ticketId}
      <button type="button" onClick={onAskAgain}>
        ask again
      </button>
    </div>
  ),
}));
vi.mock("@/stores/toast", () => ({ toast: vi.fn() }));

const ticket = (over: Partial<Ticket> = {}): Ticket => ({
  id: "t1",
  subject: "Question about A + B",
  kind: "question",
  status: "open",
  challenge_id: "p1",
  challenge_title: "A + B",
  opener_name: "mei",
  team_name: null,
  assignee_name: null,
  message_count: 2,
  created_at: "2026-10-15T10:00:00Z",
  ...over,
});

beforeEach(() => {
  clarifications = [];
  tickets = [];
  grants = ["challenge_view", "ticket_view", "ticket_respond"];
});
afterEach(() => {
  createTicket.mockClear();
  ticketsEnabled.length = 0;
});

const panel = () =>
  renderWithIntl(<ProblemClarifications competitionId="c1" challengeId="p1" challengeTitle="A + B" />);

describe("ProblemClarifications", () => {
  it("lists the judges' clarifications, question then answer", () => {
    clarifications = [
      { id: "a1", question: "Can the numbers be negative?", body: "Yes.", created_at: "2026-10-15T10:00:00Z" },
    ];
    panel();
    const list = screen.getByRole("region", { name: "Clarifications from the judges" });
    expect(within(list).getByText("Can the numbers be negative?")).toBeInTheDocument();
    expect(within(list).getByText("Yes.")).toBeInTheDocument();
  });

  it("lets a competitor ask privately, linked to the problem", () => {
    panel();
    expect(screen.getByText("Something unclear about this problem?")).toBeInTheDocument();
    expect(screen.getByText("Only the judges see your question.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ask the judges" }));
    expect(screen.getByText(/goes privately to the judges/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Your question"), {
      target: { value: "Is the input sorted?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send question" }));
    expect(createTicket.mock.calls[0][0]).toEqual({
      subject: "Question about A + B",
      body: "Is the input sorted?",
      challenge_id: "p1",
      kind: "question",
    });
  });

  it("shows only this problem's questions of theirs, and opens one", () => {
    tickets = [
      ticket(),
      ticket({ id: "t2", challenge_id: "other" }),
      // A support ticket that merely mentions the problem isn't a question.
      ticket({ id: "t3", kind: "support" }),
    ];
    panel();
    // Folded away until asked for: one quiet link.
    expect(screen.queryByRole("button", { name: /Your question ·/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Your question" }));
    const mine = screen.getAllByRole("button", { name: /Your question ·/ });
    expect(mine).toHaveLength(1);
    expect(mine[0]).toHaveTextContent("Waiting for an answer");
    fireEvent.click(mine[0]);
    expect(screen.getByText("thread t1")).toBeInTheDocument();
    // A follow-up is a new question.
    fireEvent.click(screen.getByRole("button", { name: "ask again" }));
    expect(screen.getByRole("heading", { name: "Ask the judges" })).toBeInTheDocument();
  });

  it("doesn't offer asking to staff, who answer on Support", () => {
    grants = [...grants, "ticket_assign"];
    clarifications = [{ id: "a1", question: null, body: "Limits fixed.", created_at: "2026-10-15T10:00:00Z" }];
    panel();
    expect(screen.queryByRole("button", { name: "Ask the judges" })).toBeNull();
    expect(screen.getByText("Limits fixed.")).toBeInTheDocument();
    // Nor fetches every ticket in the competition to filter.
    expect(ticketsEnabled.every((e) => e === false)).toBe(true);
  });

  it("is nothing at all for staff with no clarifications", () => {
    grants = [...grants, "ticket_assign"];
    const { container } = panel();
    expect(container).toBeEmptyDOMElement();
  });

  it("labels each clarification's question and answer", () => {
    clarifications = [
      { id: "a1", question: "Can the numbers be negative?", body: "Yes.", created_at: "2026-10-15T10:00:00Z" },
    ];
    panel();
    expect(screen.getByText("Q")).toBeInTheDocument();
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText("Question:")).toHaveClass("sr-only");
  });
});

describe("ClarificationsLink", () => {
  it("counts the clarifications in the info line and links to them", () => {
    clarifications = [
      { id: "a1", question: "Q1", body: "A1", created_at: "2026-10-15T10:00:00Z" },
      { id: "a2", question: "Q2", body: "A2", created_at: "2026-10-15T10:00:00Z" },
    ];
    renderWithIntl(<ClarificationsLink competitionId="c1" challengeId="p1" />);
    expect(screen.getByRole("link", { name: "2 clarifications" })).toHaveAttribute("href", "#clarifications");
  });

  it("says nothing when there are none", () => {
    const { container } = renderWithIntl(<ClarificationsLink competitionId="c1" challengeId="p1" />);
    expect(container).toBeEmptyDOMElement();
  });
});
