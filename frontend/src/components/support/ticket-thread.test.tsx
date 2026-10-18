import { fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { TicketThread } from "@/components/support/ticket-thread";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import type { TicketDetail, TicketMessage } from "@/lib/types";

// A competitor's thread: a question is read-only once asked (#450), an
// ordinary ticket is a conversation — and none of the staff tools appear.

let detail: TicketDetail | undefined;
let detailError = false;
let presence = { others: [] as { id: string; name: string }[], staffPresent: false };
let replyError: Error | null = null;
const reply = vi.fn();
const clarify = vi.fn();
const upload = vi.fn();

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
  useUploadTicketAttachment: () => ({ mutateAsync: upload, isPending: false }),
}));
vi.mock("@/lib/hooks/use-presence", () => ({ usePresence: () => presence }));
vi.mock("@/stores/auth", () => ({
  useAuthStore: (select: (s: { user: { id: string } }) => unknown) => select({ user: { id: "u1" } }),
}));
// Each message's attachments say whether this viewer may delete their own and
// someone else's.
vi.mock("@/components/support/ticket-attachments", () => ({
  TicketAttachments: ({ canDelete }: { canDelete: (a: { uploader_user_id: string }) => boolean }) => (
    <span data-testid="can-delete">
      {String(canDelete({ uploader_user_id: "u1" }))}/{String(canDelete({ uploader_user_id: "judge" }))}
    </span>
  ),
}));
vi.mock("@/components/support/screenshot-picker", () => ({
  ScreenshotPicker: ({ onChange }: { onChange: (f: File[]) => void }) => (
    <button type="button" data-testid="screenshots" onClick={() => onChange([new File(["x"], "shot.png")])} />
  ),
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
    assignee_user_id: null,
    last_activity_at: "2026-10-15T10:00:00Z",
    awaiting_staff: true,
    message_count: 1,
    created_at: "2026-10-15T10:00:00Z",
    messages: [message()],
  };
});
afterEach(() => {
  detailError = false;
  reply.mockReset();
  clarify.mockReset();
  upload.mockReset();
  presence = { others: [], staffPresent: false };
  replyError = null;
});

const competitor = (onAskAgain?: () => void) =>
  renderWithIntl(
    <Dialog open>
      <DialogContent>
        <TicketThread competitionId="c1" ticketId="t1" onAskAgain={onAskAgain} />
      </DialogContent>
    </Dialog>,
  );

describe("a competitor's question", () => {
  it("is read-only once sent: follow up with a new question", () => {
    const askAgain = vi.fn();
    competitor(askAgain);
    expect(screen.getByText("Question")).toBeInTheDocument();
    expect(screen.queryByLabelText("Reply")).toBeNull();
    expect(screen.getByText(/Waiting for the judges' answer/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ask a new question" }));
    expect(askAgain).toHaveBeenCalled();
  });

  it("says when it's been answered", () => {
    detail!.status = "resolved";
    competitor();
    expect(screen.getByText(/^Answered\./)).toBeInTheDocument();
    // Opened from Support there's nowhere to ask from, so no button.
    expect(screen.queryByRole("button", { name: "Ask a new question" })).toBeNull();
  });

  it("marks an answer whose clarification was withdrawn", () => {
    detail!.messages.push(
      message({ id: "m2", author_name: "judge", body: "", sent_to_all: true, withdrawn: true }),
    );
    competitor();
    expect(screen.getByText("Sent to everyone, since withdrawn")).toBeInTheDocument();
  });
});

describe("a ticket a link can't open (#508)", () => {
  it("says it isn't available instead of waiting with a reply box", () => {
    detail = undefined;
    detailError = true;
    competitor();
    expect(screen.getByText(/This ticket isn't available/)).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).toBeNull();
    expect(screen.queryByLabelText("Reply")).toBeNull();
  });
});

describe("a competitor's support ticket", () => {
  beforeEach(() => {
    detail!.kind = "support";
  });

  it("is a conversation with screenshots", () => {
    competitor();
    expect(screen.queryByText("Question")).toBeNull();
    expect(screen.getByTestId("screenshots")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Reply"), { target: { value: "Still stuck." } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(reply.mock.calls[0][0]).toEqual({ body: "Still stuck.", is_internal: false });
  });

  it("sends staged screenshots with the reply", async () => {
    reply.mockImplementation((_vars, { onSuccess }) =>
      onSuccess({ ...detail!, messages: [...detail!.messages, message({ id: "mine", author_user_id: "u1" })] }),
    );
    competitor();
    fireEvent.click(screen.getByTestId("screenshots"));
    fireEvent.change(screen.getByLabelText("Reply"), { target: { value: "here" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await vi.waitFor(() => expect(upload).toHaveBeenCalled());
    expect(upload.mock.calls[0][0]).toMatchObject({ messageId: "mine" });
  });

  it("shows the error of a failed reply", () => {
    replyError = new Error("Slow down");
    competitor();
    expect(screen.getByRole("alert")).toHaveTextContent("Slow down");
  });

  it("lets a competitor remove only their own attachments", () => {
    competitor();
    expect(screen.getByTestId("can-delete")).toHaveTextContent("true/false");
  });

  it("says when a judge is looking", () => {
    presence = { others: [{ id: "j", name: "judge" }], staffPresent: true };
    competitor();
    expect(screen.getByText("A judge is looking at this ticket")).toBeInTheDocument();
  });

  it("shows none of the staff tools", () => {
    competitor();
    for (const name of ["No comment", "Assign to me", "Resolve"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(screen.queryByText("Staff notes")).toBeNull();
  });
});
