import { fireEvent, screen } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { TicketThread } from "@/components/support/ticket-thread";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import type { TicketDetail, TicketMessage } from "@/lib/types";

// The staff side of answering a question about a problem (#450): quick
// answers, and sending the answer to everyone as a clarification — never the
// default, and only for staff who may announce.

let detail: TicketDetail;
let grants: string[];
const reply = vi.fn();
const clarify = vi.fn();

vi.mock("next/dynamic", () => ({ default: () => (() => null) as ComponentType }));
vi.mock("@/lib/hooks/use-tickets", () => ({
  useTicket: () => ({ data: detail }),
  useReplyTicket: () => ({ mutate: reply, reset: vi.fn(), isPending: false, isError: false }),
  useClarifyTicket: () => ({ mutate: clarify, reset: vi.fn(), isPending: false, isError: false }),
  useAssignTicket: () => ({ mutate: vi.fn(), isPending: false }),
  useResolveTicket: () => ({ mutate: vi.fn(), isPending: false }),
  useUploadTicketAttachment: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock("@/lib/hooks/use-presence", () => ({
  usePresence: () => ({ others: [], staffPresent: false }),
}));
vi.mock("@/lib/hooks/use-permissions", () => ({
  useAccess: () => ({ has: (p: string) => grants.includes(p) }),
}));
vi.mock("@/components/support/ticket-attachments", () => ({ TicketAttachments: () => null }));
vi.mock("@/components/support/screenshot-picker", () => ({
  ScreenshotPicker: () => <div data-testid="screenshots" />,
}));
vi.mock("@/stores/toast", () => ({ toast: vi.fn() }));

const message = (over: Partial<TicketMessage> = {}): TicketMessage => ({
  id: "m1",
  author_user_id: "u1",
  author_name: "mei",
  body: "Hi, Mei here — can the numbers be negative?",
  is_internal: false,
  sent_to_all: false,
  created_at: "2026-10-15T10:00:00Z",
  attachments: [],
  ...over,
});

beforeEach(() => {
  detail = {
    id: "t1",
    subject: "Question about A + B",
    kind: "question",
    status: "open",
    challenge_id: "p1",
    challenge_title: "A + B",
    opener_name: "mei",
    team_name: null,
    assignee_name: null,
    message_count: 1,
    created_at: "2026-10-15T10:00:00Z",
    messages: [message()],
  };
  grants = ["ticket_view", "ticket_respond", "ticket_assign", "announcement_create"];
});
afterEach(() => {
  reply.mockClear();
  clarify.mockClear();
});

const thread = (isStaff = true) =>
  renderWithIntl(
    <Dialog open>
      <DialogContent>
        <TicketThread competitionId="c1" ticketId="t1" isStaff={isStaff} />
      </DialogContent>
    </Dialog>,
  );

describe("answering a question about a problem", () => {
  it("is labelled a question, answered in text only", () => {
    thread();
    expect(screen.getByText("Question")).toBeInTheDocument();
    expect(screen.getByText("unanswered")).toBeInTheDocument();
    expect(screen.getByLabelText("Reply")).toHaveAttribute("placeholder", "Your answer…");
    expect(screen.queryByTestId("screenshots")).toBeNull();
  });

  it("keeps screenshots and the plain labels on an ordinary ticket", () => {
    detail.kind = "support";
    thread();
    expect(screen.queryByText("Question")).toBeNull();
    expect(screen.getByTestId("screenshots")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  it("offers quick answers that fill the reply", () => {
    thread();
    fireEvent.click(screen.getByRole("button", { name: "No comment" }));
    expect(screen.getByLabelText("Reply")).toHaveValue("No comment.");
  });

  it("replies privately by default", () => {
    thread();
    fireEvent.change(screen.getByLabelText("Reply"), { target: { value: "Yes." } });
    fireEvent.click(screen.getByRole("button", { name: "Send answer" }));
    expect(reply.mock.calls[0][0]).toEqual({ body: "Yes.", is_internal: false });
    expect(clarify).not.toHaveBeenCalled();
  });

  it("sends to everyone with the question as the judge words it", () => {
    thread();
    fireEvent.click(screen.getByLabelText("Also send to everyone as a clarification"));
    // Seeded from the asker's message, for the judge to edit.
    const question = screen.getByLabelText("The question, as everyone will see it");
    expect(question).toHaveValue("Hi, Mei here — can the numbers be negative?");
    // An internal note can't go to everyone.
    expect(screen.getByLabelText("Internal note")).toBeDisabled();
    // A clarification is text only — screenshots would reach just the asker.
    expect(screen.queryByTestId("screenshots")).toBeNull();
    fireEvent.change(question, { target: { value: "Can the numbers be negative?" } });
    fireEvent.change(screen.getByLabelText("Reply"), { target: { value: "Yes." } });
    fireEvent.click(screen.getByRole("button", { name: "Send to everyone" }));
    expect(clarify.mock.calls[0][0]).toEqual({ question: "Can the numbers be negative?", answer: "Yes." });
    expect(reply).not.toHaveBeenCalled();
  });

  it("marks an answer whose clarification was withdrawn, and hides it from the asker", () => {
    detail.messages.push(
      message({ id: "m2", author_name: "judge", body: "", sent_to_all: true, withdrawn: true }),
    );
    thread(false);
    expect(screen.getByText("Sent to everyone, since withdrawn")).toBeInTheDocument();
  });

  it("marks an answer that went to everyone", () => {
    detail.messages.push(message({ id: "m2", author_name: "judge", body: "Yes.", sent_to_all: true }));
    thread();
    expect(screen.getByText("Sent to everyone")).toBeInTheDocument();
  });

  it("can't send to everyone without permission to announce", () => {
    grants = grants.filter((g) => g !== "announcement_create");
    thread();
    expect(screen.queryByLabelText("Also send to everyone as a clarification")).toBeNull();
    expect(screen.getByRole("button", { name: "No comment" })).toBeInTheDocument();
  });

  it("keeps a general support ticket plain", () => {
    detail.challenge_id = null;
    thread();
    expect(screen.queryByRole("button", { name: "No comment" })).toBeNull();
    expect(screen.queryByLabelText("Also send to everyone as a clarification")).toBeNull();
  });

  it("shows a competitor none of it", () => {
    thread(false);
    expect(screen.queryByRole("button", { name: "No comment" })).toBeNull();
    expect(screen.queryByLabelText("Also send to everyone as a clarification")).toBeNull();
  });

});

describe("a competitor's question", () => {
  const competitor = (onAskAgain?: () => void) =>
    renderWithIntl(
      <Dialog open>
        <DialogContent>
          <TicketThread competitionId="c1" ticketId="t1" isStaff={false} onAskAgain={onAskAgain} />
        </DialogContent>
      </Dialog>,
    );

  it("is read-only once sent: follow up with a new question", () => {
    const askAgain = vi.fn();
    competitor(askAgain);
    expect(screen.queryByLabelText("Reply")).toBeNull();
    expect(screen.getByText(/Waiting for the judges' answer/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ask a new question" }));
    expect(askAgain).toHaveBeenCalled();
  });

  it("says when it's been answered", () => {
    detail.status = "resolved";
    competitor();
    expect(screen.getByText(/^Answered\./)).toBeInTheDocument();
    // Opened from Support there's nowhere to ask from, so no button.
    expect(screen.queryByRole("button", { name: "Ask a new question" })).toBeNull();
  });

  it("leaves an ordinary support ticket a conversation", () => {
    detail.kind = "support";
    competitor();
    expect(screen.getByLabelText("Reply")).toBeInTheDocument();
  });
});
