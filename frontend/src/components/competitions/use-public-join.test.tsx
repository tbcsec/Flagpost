import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { usePublicJoin } from "@/components/competitions/use-public-join";
import { renderWithIntl } from "@/test/intl";

// The public join shared by the lobby and the join panel (#478): fields, then
// rules, then the join — and the email-verification gate routed to Profile.

const push = vi.fn();
const mutate = vi.fn();
const acceptMutate = vi.fn();
const fetchRules = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/hooks/use-competitions", () => ({
  useJoinCompetition: () => ({ mutate, isPending: false }),
}));
vi.mock("@/lib/hooks/use-rules", () => ({
  useFetchRules: () => fetchRules,
  useAcceptRules: () => ({ mutate: acceptMutate, isPending: false }),
}));
// The fields dialog submits these answers at once.
vi.mock("@/components/registration/join-fields-dialog", () => ({
  JoinFieldsDialog: ({ onSubmit }: { onSubmit: (v: Record<string, string>) => void }) => (
    <button onClick={() => onSubmit({ diet: "vegan" })}>submit fields</button>
  ),
}));
vi.mock("@/components/competitions/rules-accept-modal", () => ({
  RulesAcceptModal: ({ mode, onConfirm }: { mode: string; onConfirm: () => void }) => (
    <button onClick={onConfirm}>confirm {mode}</button>
  ),
}));
const toast = vi.fn();
vi.mock("@/stores/toast", () => ({ toast: (...a: unknown[]) => toast(...a) }));

const onJoined = vi.fn();
function Harness() {
  const join = usePublicJoin({ onJoined });
  return (
    <>
      <button onClick={() => join.start("c1", "Spring CTF")}>start</button>
      {join.dialogs}
    </>
  );
}

beforeEach(() => {
  for (const f of [push, mutate, acceptMutate, fetchRules, onJoined, toast]) f.mockReset();
});

async function startAndSubmit() {
  renderWithIntl(<Harness />);
  fireEvent.click(screen.getByText("start"));
  fireEvent.click(screen.getByText("submit fields"));
}

describe("usePublicJoin", () => {
  it("joins with the field answers when there are no rules", async () => {
    fetchRules.mockResolvedValue({ rules: null, display_only: false, accepted: false, exempt: false });
    mutate.mockImplementation((_vars, { onSuccess }) => onSuccess());
    await startAndSubmit();
    await waitFor(() => expect(mutate).toHaveBeenCalled());
    expect(mutate.mock.calls[0][0]).toEqual({ id: "c1", fieldValues: { diet: "vegan" } });
    expect(onJoined).toHaveBeenCalledWith("Spring CTF");
  });

  it("asks for the rules to be accepted first, then joins", async () => {
    fetchRules.mockResolvedValue({
      rules: { type: "doc", content: [] },
      display_only: false,
      accepted: false,
      exempt: false,
    });
    acceptMutate.mockImplementation((_id, { onSuccess }) => onSuccess());
    mutate.mockImplementation((_vars, { onSuccess }) => onSuccess());
    await startAndSubmit();
    const confirm = await screen.findByText("confirm accept");
    expect(mutate).not.toHaveBeenCalled();
    act(() => fireEvent.click(confirm));
    expect(acceptMutate.mock.calls[0][0]).toBe("c1");
    expect(onJoined).toHaveBeenCalledWith("Spring CTF");
  });

  it("joins only once acceptance has been recorded", async () => {
    fetchRules.mockResolvedValue({
      rules: { type: "doc", content: [] },
      display_only: false,
      accepted: false,
      exempt: false,
    });
    let accepted: () => void = () => {};
    acceptMutate.mockImplementation((_id, { onSuccess }) => (accepted = onSuccess));
    mutate.mockImplementation((_vars, { onSuccess }) => onSuccess());
    await startAndSubmit();
    const confirm = await screen.findByText("confirm accept");
    act(() => fireEvent.click(confirm));
    await waitFor(() => expect(acceptMutate).toHaveBeenCalled());
    expect(mutate).not.toHaveBeenCalled();
    act(() => accepted());
    expect(mutate).toHaveBeenCalled();
  });

  it("shows display-only rules, then joins without an acceptance", async () => {
    fetchRules.mockResolvedValue({
      rules: { type: "doc", content: [] },
      display_only: true,
      accepted: false,
      exempt: false,
    });
    mutate.mockImplementation((_vars, { onSuccess }) => onSuccess());
    await startAndSubmit();
    const confirm = await screen.findByText("confirm display");
    act(() => fireEvent.click(confirm));
    expect(acceptMutate).not.toHaveBeenCalled();
    expect(onJoined).toHaveBeenCalledWith("Spring CTF");
  });

  it("still tries the join when the rules can't be checked", async () => {
    fetchRules.mockRejectedValue(new Error("network"));
    await startAndSubmit();
    await waitFor(() => expect(mutate).toHaveBeenCalled());
  });

  it("sends an unverified email to the Profile page", async () => {
    fetchRules.mockResolvedValue(null);
    mutate.mockImplementation((_vars, { onError }) =>
      onError({ status: 403, message: "Verify your email to join a competition" }),
    );
    await startAndSubmit();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/profile"));
    expect(onJoined).not.toHaveBeenCalled();
  });
});
