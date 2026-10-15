import { fireEvent, screen, waitFor, within } from "@testing-library/react";
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

const postClarification = vi.fn();
const withdrawClarification = vi.fn();
vi.mock("@/lib/hooks/use-announcements", () => ({
  useClarifications: () => ({ data: clarifications }),
  usePostClarification: () => ({ mutate: postClarification, isPending: false, isError: false }),
  useWithdrawClarification: () => ({ mutate: withdrawClarification, isPending: false }),
}));
vi.mock("@/components/ui/confirm", () => ({ useConfirm: () => () => Promise.resolve(true) }));
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
  postClarification.mockClear();
  withdrawClarification.mockClear();
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

describe("withdrawn clarifications", () => {
  it("stay listed, marked withdrawn, without their answer", () => {
    clarifications = [
      {
        id: "a1",
        question: "Can the numbers be negative?",
        body: "",
        created_at: "2026-10-15T10:00:00Z",
        withdrawn_at: "2026-10-15T11:00:00Z",
      },
    ];
    panel();
    expect(screen.getByText("Withdrawn by the judges")).toBeInTheDocument();
    expect(screen.getByText("Can the numbers be negative?")).toBeInTheDocument();
    expect(screen.queryByText("Answer:")).toBeNull();
  });

  it("don't count towards the info line's link", () => {
    clarifications = [
      { id: "a1", question: null, body: "", created_at: "2026-10-15T10:00:00Z", withdrawn_at: "2026-10-15T11:00:00Z" },
    ];
    const { container } = renderWithIntl(<ClarificationsLink competitionId="c1" challengeId="p1" />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("for staff", () => {
  beforeEach(() => {
    grants = ["challenge_view", "ticket_view", "ticket_respond", "ticket_assign", "announcement_create", "announcement_delete"];
  });

  it("posts a clarification without a question", () => {
    panel();
    expect(screen.getByText("No clarifications yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Post a clarification" }));
    fireEvent.change(screen.getByLabelText("Clarification"), {
      target: { value: "The input ends with a newline." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send to everyone" }));
    expect(postClarification.mock.calls[0][0]).toEqual({
      body: "The input ends with a newline.",
      question: null,
    });
  });

  it("withdraws one, after confirming", async () => {
    clarifications = [{ id: "a1", question: "Q?", body: "Yes.", created_at: "2026-10-15T10:00:00Z" }];
    panel();
    fireEvent.click(screen.getByRole("button", { name: "Withdraw" }));
    await waitFor(() => expect(withdrawClarification.mock.calls[0][0]).toBe("a1"));
  });

  it("keeps a withdrawn answer in their history, struck through, and can't withdraw it twice", () => {
    clarifications = [
      { id: "a1", question: "Q?", body: "Yes.", created_at: "2026-10-15T10:00:00Z", withdrawn_at: "2026-10-15T11:00:00Z" },
    ];
    panel();
    expect(screen.getByText("Yes.").closest("p")).toHaveClass("line-through");
    expect(screen.queryByRole("button", { name: "Withdraw" })).toBeNull();
  });
});

describe("in a flag challenge's dialog", () => {
  it("shows clarifications but offers no asking", () => {
    clarifications = [{ id: "a1", question: null, body: "Flags are case-sensitive.", created_at: "2026-10-15T10:00:00Z" }];
    renderWithIntl(
      <ProblemClarifications competitionId="c1" challengeId="p1" challengeTitle="Web 1" allowAsk={false} />,
    );
    expect(screen.getByText("Flags are case-sensitive.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ask the judges" })).toBeNull();
    // A clarification with no question reads as a plain note, no Q/A labels.
    expect(screen.queryByText("A")).toBeNull();
  });

  it("is nothing at all for a competitor when there are none", () => {
    const { container } = renderWithIntl(
      <ProblemClarifications competitionId="c1" challengeId="p1" challengeTitle="Web 1" allowAsk={false} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
