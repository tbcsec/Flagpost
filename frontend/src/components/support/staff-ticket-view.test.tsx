import { fireEvent, screen } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { StaffTicketView } from "@/components/support/staff-ticket-view";
import type { TicketDetail, TicketMessage } from "@/lib/types";

// A ticket as staff work it (#503): its details and actions apart from the
// message, and the message's kind chosen explicitly — reply, internal note, or
// a clarification for everyone (#450, only for staff who may announce).

let detail: TicketDetail | undefined;
let detailError = false;
let grants: string[];
let presence = { others: [] as { id: string; name: string }[], staffPresent: false };
let replyError: Error | null = null;
const reply = vi.fn();
const clarify = vi.fn();
const assign = vi.fn();
const resolve = vi.fn();
const upload = vi.fn();
const toast = vi.fn();

vi.mock("next/dynamic", () => ({
  default: () => (() => <div data-testid="staff-notes-pad" />) as ComponentType,
}));
vi.mock("@/lib/hooks/use-tickets", () => ({
  useTicket: () => ({ data: detail, isError: detailError }),
  useReplyTicket: () => ({
    mutate: reply,
    reset: vi.fn(),
    isPending: false,
    isError: Boolean(replyError),
    error: replyError,
  }),
  useClarifyTicket: () => ({ mutate: clarify, reset: vi.fn(), isPending: false, isError: false }),
  useAssignTicket: () => ({ mutate: assign, isPending: false }),
  useResolveTicket: () => ({ mutate: resolve, isPending: false }),
  useUploadTicketAttachment: () => ({ mutateAsync: upload, isPending: false }),
}));
vi.mock("@/lib/hooks/use-presence", () => ({ usePresence: () => presence }));
vi.mock("@/lib/hooks/use-permissions", () => ({
  useAccess: () => ({ has: (p: string) => grants.includes(p) }),
}));
vi.mock("@/stores/auth", () => ({
  useAuthStore: (select: (s: { user: { id: string } }) => unknown) => select({ user: { id: "judge-1" } }),
}));
// Each message's attachments say whether this viewer may delete someone else's.
vi.mock("@/components/support/ticket-attachments", () => ({
  TicketAttachments: ({ canDelete }: { canDelete: (a: { uploader_user_id: string }) => boolean }) => (
    <span data-testid="can-delete-others">{String(canDelete({ uploader_user_id: "someone-else" }))}</span>
  ),
}));
// A picker that stages one file when clicked and shows how many are staged.
vi.mock("@/components/support/screenshot-picker", () => ({
  ScreenshotPicker: ({ files, onChange }: { files: File[]; onChange: (f: File[]) => void }) => (
    <button type="button" data-testid="screenshots" onClick={() => onChange([new File(["x"], "shot.png")])}>
      {files.length} staged
    </button>
  ),
}));
vi.mock("@/stores/toast", () => ({ toast: (...a: unknown[]) => toast(...a) }));

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
  detailError = false;
  presence = { others: [], staffPresent: false };
  replyError = null;
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
    assignee_user_id: null,
    last_activity_at: "2026-10-15T10:00:00Z",
    awaiting_staff: true,
    message_count: 1,
    created_at: "2026-10-15T10:00:00Z",
    messages: [message()],
  };
  grants = ["ticket_view", "ticket_respond", "ticket_assign", "announcement_create"];
});
afterEach(() => {
  for (const f of [reply, clarify, assign, resolve, upload, toast]) f.mockReset();
});

const view = () => renderWithIntl(<StaffTicketView competitionId="c1" ticketId="t1" />);
const mode = (name: string) => screen.getByRole("radio", { name });
const box = (name: string) => screen.getByRole("textbox", { name });
/** Make the reply call succeed with our own message appended to the thread. */
function replySucceeds() {
  reply.mockImplementation((_vars, { onSuccess }) =>
    onSuccess({ ...detail!, messages: [...detail!.messages, message({ id: "mine", author_user_id: "judge-1" })] }),
  );
}

describe("the ticket's details and actions", () => {
  it("lays out who, what and where it stands", () => {
    view();
    expect(screen.getByRole("heading", { name: "Question about A + B" })).toBeInTheDocument();
    expect(screen.getByText("unanswered")).toBeInTheDocument();
    expect(screen.getAllByText("Waiting on staff").length).toBeGreaterThan(0);
    expect(screen.getByText("From").nextSibling).toHaveTextContent("mei");
    expect(screen.getByText("Challenge").nextSibling).toHaveTextContent("A + B");
    expect(screen.getByText("Assigned to").nextSibling).toHaveTextContent("Unassigned");
  });

  it("assigns and resolves apart from the message", () => {
    view();
    fireEvent.click(screen.getByRole("button", { name: "Assign to me" }));
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
    expect(assign).toHaveBeenCalled();
    expect(resolve).toHaveBeenCalled();
    expect(reply).not.toHaveBeenCalled();
  });

  it("says when it's already yours, and offers no Resolve once resolved", () => {
    detail = { ...detail!, assignee_user_id: "judge-1", assignee_name: "judge", status: "resolved" };
    view();
    expect(screen.getByText("Assigned to you")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Assign to me" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Resolve" })).toBeNull();
  });

  it("keeps staff notes on their own tab", () => {
    view();
    expect(screen.queryByTestId("staff-notes-pad")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Staff notes" }));
    expect(screen.getByTestId("staff-notes-pad")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("confirms an assignment", () => {
    assign.mockImplementation((_v, { onSuccess }) => onSuccess());
    view();
    fireEvent.click(screen.getByRole("button", { name: "Assign to me" }));
    expect(toast).toHaveBeenCalledWith("Assigned to you");
  });

  it("moves focus to the ticket when it opens", () => {
    view();
    expect(screen.getByRole("heading", { name: "Question about A + B" })).toHaveFocus();
  });

  it("shows other staff on the ticket, never the competitor's banner", () => {
    presence = { others: [{ id: "x", name: "ana" }], staffPresent: true };
    view();
    expect(screen.getByText("1 other here")).toBeInTheDocument();
    expect(screen.queryByText("A judge is looking at this ticket")).toBeNull();
  });

  it("lets staff remove anyone's attachment", () => {
    view();
    expect(screen.getAllByTestId("can-delete-others")[0]).toHaveTextContent("true");
  });

  it("keeps a loaded ticket on screen when a refetch fails", () => {
    detailError = true;
    view();
    expect(screen.getByRole("heading", { name: "Question about A + B" })).toBeInTheDocument();
  });

  it("explains a ticket that can't be loaded", () => {
    detail = undefined;
    detailError = true;
    view();
    expect(screen.getByText(/This ticket isn't available/)).toBeInTheDocument();
  });
});

describe("answering a question about a problem", () => {
  it("answers in text only, privately by default", () => {
    view();
    expect(mode("Answer")).toBeChecked();
    expect(screen.getByText("mei will see this.")).toBeInTheDocument();
    expect(box("Answer")).toHaveAttribute("placeholder", "Your answer…");
    expect(box("Answer")).toHaveAccessibleDescription("mei will see this.");
    expect(screen.queryByTestId("screenshots")).toBeNull();
    fireEvent.change(box("Answer"), { target: { value: "Yes." } });
    fireEvent.click(screen.getByRole("button", { name: "Send answer" }));
    expect(reply.mock.calls[0][0]).toEqual({ body: "Yes.", is_internal: false });
    expect(clarify).not.toHaveBeenCalled();
  });

  it("offers quick answers that fill the reply", () => {
    view();
    fireEvent.click(screen.getByRole("button", { name: "No comment" }));
    expect(box("Answer")).toHaveValue("No comment.");
    // Not for an internal note.
    fireEvent.click(mode("Internal note"));
    expect(screen.queryByRole("button", { name: "No comment" })).toBeNull();
  });

  it("clears the clarification's question once it's sent", async () => {
    clarify.mockImplementation((_vars, { onSuccess }) =>
      onSuccess({ ...detail!, messages: [...detail!.messages, message({ id: "mine", author_user_id: "judge-1" })] }),
    );
    view();
    fireEvent.click(mode("Clarification for everyone"));
    fireEvent.change(screen.getByLabelText("The question, as everyone will see it"), {
      target: { value: "Negative?" },
    });
    fireEvent.change(box("Clarification for everyone"), { target: { value: "Yes." } });
    fireEvent.click(screen.getByRole("button", { name: "Send to everyone" }));
    await vi.waitFor(() => expect(mode("Answer")).toBeChecked());
    expect(toast).toHaveBeenCalledWith(expect.stringMatching(/posted to everyone/), { variant: "success" });
    // Choosing it again re-seeds from the asker's message rather than keeping
    // the last one sent.
    fireEvent.click(mode("Clarification for everyone"));
    expect(screen.getByLabelText("The question, as everyone will see it")).toHaveValue(
      "Hi, Mei here — can the numbers be negative?",
    );
  });

  it("sends to everyone with the question as the judge words it", () => {
    view();
    fireEvent.click(mode("Clarification for everyone"));
    // Seeded from the asker's message, for the judge to edit.
    const question = screen.getByLabelText("The question, as everyone will see it");
    expect(question).toHaveValue("Hi, Mei here — can the numbers be negative?");
    expect(screen.queryByTestId("screenshots")).toBeNull();
    fireEvent.change(question, { target: { value: "Can the numbers be negative?" } });
    fireEvent.change(box("Clarification for everyone"), { target: { value: "Yes." } });
    fireEvent.click(screen.getByRole("button", { name: "Send to everyone" }));
    expect(clarify.mock.calls[0][0]).toEqual({ question: "Can the numbers be negative?", answer: "Yes." });
    expect(reply).not.toHaveBeenCalled();
  });

  it("can't send to everyone without permission to announce", () => {
    grants = grants.filter((g) => g !== "announcement_create");
    view();
    expect(screen.queryByRole("radio", { name: "Clarification for everyone" })).toBeNull();
    expect(screen.getByRole("button", { name: "No comment" })).toBeInTheDocument();
  });

  it("marks an answer that went to everyone, and one since withdrawn", () => {
    detail!.messages.push(
      message({ id: "m2", author_name: "judge", body: "Yes.", sent_to_all: true }),
      message({ id: "m3", author_name: "judge", body: "No.", sent_to_all: true, withdrawn: true }),
    );
    view();
    expect(screen.getByText("Sent to everyone")).toBeInTheDocument();
    expect(screen.getByText("Sent to everyone, since withdrawn")).toBeInTheDocument();
  });
});

describe("an ordinary support ticket", () => {
  beforeEach(() => {
    detail = { ...detail!, kind: "support", challenge_id: null, challenge_title: null };
  });

  it("replies with screenshots, and has no clarification or quick answers", () => {
    view();
    expect(mode("Reply")).toBeChecked();
    expect(screen.getByTestId("screenshots")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Clarification for everyone" })).toBeNull();
    expect(screen.queryByRole("button", { name: "No comment" })).toBeNull();
  });

  it("writes an internal note in its own, marked mode", () => {
    view();
    fireEvent.click(mode("Internal note"));
    expect(box("Internal note")).toHaveAccessibleDescription("Only staff see internal notes.");
    fireEvent.change(box("Internal note"), { target: { value: "Dupe of #12." } });
    fireEvent.click(screen.getByRole("button", { name: "Add note" }));
    expect(reply.mock.calls[0][0]).toEqual({ body: "Dupe of #12.", is_internal: true });
  });

  it("attaches screenshots to an internal note too", async () => {
    replySucceeds();
    view();
    fireEvent.click(mode("Internal note"));
    fireEvent.click(screen.getByTestId("screenshots"));
    fireEvent.change(box("Internal note"), { target: { value: "see screenshot" } });
    fireEvent.click(screen.getByRole("button", { name: "Add note" }));
    await vi.waitFor(() => expect(upload).toHaveBeenCalled());
    expect(upload.mock.calls[0][0]).toMatchObject({ ticketId: "t1", messageId: "mine" });
  });

  it("goes back to a reply once a note is sent", () => {
    replySucceeds();
    view();
    fireEvent.click(mode("Internal note"));
    fireEvent.change(box("Internal note"), { target: { value: "noted" } });
    fireEvent.click(screen.getByRole("button", { name: "Add note" }));
    return vi.waitFor(() => {
      expect(mode("Reply")).toBeChecked();
      expect(box("Reply")).toHaveValue("");
    });
  });

  it("drops staged screenshots when switching to a clarification", () => {
    detail = { ...detail!, challenge_id: "p1", challenge_title: "A + B" };
    view();
    fireEvent.click(screen.getByTestId("screenshots"));
    expect(screen.getByTestId("screenshots")).toHaveTextContent("1 staged");
    fireEvent.click(mode("Clarification for everyone"));
    fireEvent.click(mode("Reply"));
    expect(screen.getByTestId("screenshots")).toHaveTextContent("0 staged");
  });

  it("shows the error of what was just sent", () => {
    replyError = new Error("Too many replies");
    view();
    expect(screen.getByRole("alert")).toHaveTextContent("Too many replies");
  });
});
