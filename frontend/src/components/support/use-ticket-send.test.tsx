import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useTicketSend } from "@/components/support/use-ticket-send";
import type { TicketDetail, TicketMessage } from "@/lib/types";
import { IntlProvider } from "@/test/intl";

// Sending on a ticket (#503): the message, then screenshots attached to *our*
// message, with the clarification and partial-upload toasts.

const reply = vi.fn();
const clarify = vi.fn();
const upload = vi.fn();
const toast = vi.fn();
vi.mock("@/lib/hooks/use-tickets", () => ({
  useReplyTicket: () => ({ mutate: reply, reset: vi.fn(), isPending: false, isError: false }),
  useClarifyTicket: () => ({ mutate: clarify, reset: vi.fn(), isPending: false, isError: false }),
  useUploadTicketAttachment: () => ({ mutateAsync: upload, isPending: false }),
}));
vi.mock("@/stores/auth", () => ({
  useAuthStore: (select: (s: { user: { id: string } }) => unknown) => select({ user: { id: "me" } }),
}));
vi.mock("@/stores/toast", () => ({ toast: (...a: unknown[]) => toast(...a) }));

const msg = (id: string, author: string): TicketMessage => ({
  id,
  author_user_id: author,
  author_name: author,
  body: "",
  is_internal: false,
  sent_to_all: false,
  created_at: "2026-10-18T10:00:00Z",
  attachments: [],
});
const thread = (messages: TicketMessage[]) => ({ messages }) as unknown as TicketDetail;
const shot = (name: string) => new File(["x"], name);

beforeEach(() => {
  for (const f of [reply, clarify, upload, toast]) f.mockReset();
});

function hook() {
  return renderHook(() => useTicketSend("c1", "t1"), { wrapper: IntlProvider }).result;
}

describe("useTicketSend", () => {
  it("attaches screenshots to our own latest message, not someone else's", async () => {
    // Someone replied while ours was in flight: theirs is last.
    reply.mockImplementation((_v, { onSuccess }) => onSuccess(thread([msg("old", "me"), msg("ours", "me"), msg("theirs", "judge")])));
    const onSent = vi.fn();
    const result = hook();
    await act(async () => result.current.send({ mode: "reply", body: "hi", files: [shot("a.png")] }, { onSent }));
    expect(reply.mock.calls[0][0]).toEqual({ body: "hi", is_internal: false });
    expect(upload.mock.calls[0][0]).toMatchObject({ ticketId: "t1", messageId: "ours" });
    expect(onSent).toHaveBeenCalled();
    expect(toast).not.toHaveBeenCalled();
  });

  it("says which screenshots couldn't be attached", async () => {
    reply.mockImplementation((_v, { onSuccess }) => onSuccess(thread([msg("ours", "me")])));
    upload.mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error("too big"));
    const result = hook();
    await act(async () =>
      result.current.send({ mode: "internal", body: "n", files: [shot("a.png"), shot("b.png")] }, { onSent: vi.fn() }),
    );
    expect(reply.mock.calls[0][0]).toEqual({ body: "n", is_internal: true });
    expect(toast).toHaveBeenCalledWith("Reply sent, but b.png couldn't be attached", { variant: "destructive" });
  });

  it("reports every file when our message can't be found", async () => {
    reply.mockImplementation((_v, { onSuccess }) => onSuccess(thread([msg("theirs", "judge")])));
    const result = hook();
    await act(async () => result.current.send({ mode: "reply", body: "x", files: [shot("a.png")] }, { onSent: vi.fn() }));
    expect(upload).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith("Reply sent, but a.png couldn't be attached", { variant: "destructive" });
  });

  it("sends a clarification through its own endpoint and says so", async () => {
    clarify.mockImplementation((_v, { onSuccess }) => onSuccess(thread([msg("ours", "me")])));
    const result = hook();
    await act(async () =>
      result.current.send({ mode: "everyone", body: "Yes.", question: "Negative?" }, { onSent: vi.fn() }),
    );
    expect(clarify.mock.calls[0][0]).toEqual({ question: "Negative?", answer: "Yes." });
    expect(reply).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(expect.stringMatching(/posted to everyone/), { variant: "success" });
  });
});
