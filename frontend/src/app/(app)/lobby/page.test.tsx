import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LobbyPage from "@/app/(app)/lobby/page";
import { renderWithIntl } from "@/test/intl";

// The lobby serves first-timers and, since #478, members joining another event:
// joined competitions read "Joined" with Open instead of Join.

const push = vi.fn();
const start = vi.fn();
const codeMutate = vi.fn();
const fetchRules = vi.fn();
let publicOnJoined: (name: string) => void = () => {};
const setActiveCompetition = vi.fn();
let inLobby = true;
let memberOf = new Set<string>();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/hooks/use-competitions", () => ({
  useCompetitions: () => ({
    data: [
      { id: "c1", name: "Spring CTF", visibility: "public", participation_mode: "team", archived_at: null },
      { id: "c2", name: "Autumn CTF", visibility: "public", participation_mode: "individual", archived_at: null },
      { id: "c3", name: "Old CTF", visibility: "public", participation_mode: "team", archived_at: "2026-01-01T00:00:00Z" },
    ],
  }),
  useJoinByCode: () => ({ mutate: codeMutate, isPending: false }),
}));
vi.mock("@/lib/hooks/use-permissions", () => ({
  useAccess: () => ({ ready: true, inLobby, isMemberOf: (id: string) => memberOf.has(id) }),
}));
vi.mock("@/lib/hooks/use-rules", () => ({
  useFetchRules: () => fetchRules,
  useAcceptRules: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/components/competitions/use-public-join", () => ({
  usePublicJoin: ({ onJoined }: { onJoined: (name: string) => void }) => {
    publicOnJoined = onJoined;
    return { start, isPending: false, dialogs: null };
  },
  useJoinErrorHandler: () => vi.fn(),
}));
vi.mock("@/stores/auth", () => ({
  useAuthStore: (select: (s: { setActiveCompetition: typeof setActiveCompetition }) => unknown) =>
    select({ setActiveCompetition }),
}));
vi.mock("@/stores/toast", () => ({ toast: vi.fn() }));
vi.mock("@/components/competitions/rules-accept-modal", () => ({
  RulesAcceptModal: ({ mode, onConfirm }: { mode: string; onConfirm: () => void }) => (
    <button onClick={onConfirm}>confirm {mode}</button>
  ),
}));

beforeEach(() => {
  push.mockReset();
  start.mockReset();
  codeMutate.mockReset();
  fetchRules.mockReset();
  setActiveCompetition.mockReset();
  inLobby = true;
  memberOf = new Set();
});

describe("LobbyPage", () => {
  it("welcomes a first-timer and lists open public competitions to join", () => {
    renderWithIntl(<LobbyPage />);
    expect(screen.getByText("You're not currently part of any competition.")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Join" })).toHaveLength(3); // two + invite
    expect(screen.queryByText("Old CTF")).toBeNull();
    fireEvent.click(screen.getAllByRole("button", { name: "Join" })[1]);
    expect(start).toHaveBeenCalledWith("c1", "Spring CTF");
  });

  it("lets a member open the ones they're in and join the rest", () => {
    inLobby = false;
    memberOf = new Set(["c1"]);
    renderWithIntl(<LobbyPage />);
    expect(screen.getByText(/Join another competition/)).toBeInTheDocument();
    expect(screen.getByText("Joined")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(setActiveCompetition).toHaveBeenCalledWith("c1");
    expect(push).toHaveBeenCalledWith("/");
    // Autumn CTF is still joinable (plus the invite-code Join).
    expect(screen.getAllByRole("button", { name: "Join" })).toHaveLength(2);
  });

  it("goes to the dashboard after a public join", () => {
    renderWithIntl(<LobbyPage />);
    publicOnJoined("Spring CTF");
    expect(push).toHaveBeenCalledWith("/");
  });

  it("shows display-only rules after an invite-code join, then goes on", async () => {
    codeMutate.mockImplementation((_vars, { onSuccess }) => onSuccess({ id: "p", name: "Winter" }));
    fetchRules.mockResolvedValue({
      rules: { type: "doc", content: [] },
      display_only: true,
      accepted: false,
      exempt: false,
    });
    renderWithIntl(<LobbyPage />);
    fireEvent.change(screen.getByPlaceholderText("Invite code"), { target: { value: "abc" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Join" })[0]);
    const confirm = await screen.findByText("confirm display");
    expect(push).not.toHaveBeenCalled();
    fireEvent.click(confirm);
    expect(push).toHaveBeenCalledWith("/");
  });
});
