import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { InviteLinksPanel } from "@/components/competitions/invite-links-panel";
import type { InviteLink } from "@/lib/types";

const mockCreate = vi.fn();
const mockRevoke = vi.fn();
let mockLinks: InviteLink[] = [];

vi.mock("@/lib/hooks/use-invite-links", () => ({
  useInviteLinks: () => ({ data: mockLinks, isLoading: false, isError: false }),
  useCreateInviteLink: () => ({ mutate: mockCreate, isPending: false, error: null }),
  useRevokeInviteLink: () => ({ mutate: mockRevoke, isPending: false }),
}));

vi.mock("@/components/ui/confirm", () => ({
  useConfirm: () => () => Promise.resolve(true),
}));

vi.mock("@/stores/toast", () => ({ toast: vi.fn() }));

afterEach(() => {
  mockCreate.mockReset();
  mockRevoke.mockClear();
  mockLinks = [];
});

function makeLink(overrides: Partial<InviteLink> = {}): InviteLink {
  return {
    id: "l1",
    competition_id: "c1",
    token: "tok123",
    capability: "join",
    label: "sponsor email",
    expires_at: null,
    max_uses: null,
    use_count: 3,
    last_used_at: null,
    revoked_at: null,
    created_at: "2026-10-13T09:00:00Z",
    active: true,
    ...overrides,
  };
}

describe("InviteLinksPanel", () => {
  it("creates a join link and reveals the URL", () => {
    const created = makeLink({ token: "freshtok" });
    mockCreate.mockImplementation((_payload, opts) => opts.onSuccess(created));
    renderWithIntl(<InviteLinksPanel competitionId="c1" visibility="private" />);

    expect(screen.getByText("No links yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "New link" }));
    fireEvent.change(screen.getByLabelText("Label (optional)"), {
      target: { value: "  Discord blast  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create link" }));

    expect(mockCreate).toHaveBeenCalledTimes(1);
    expect(mockCreate.mock.calls[0][0]).toEqual({
      capability: "join",
      label: "Discord blast",
      expires_at: null,
      max_uses: null,
    });
    // The created dialog shows the full landing URL for this token.
    expect(screen.getByDisplayValue(/\/invite\/freshtok$/)).toBeInTheDocument();
  });

  it("offers the view capability only for public competitions", () => {
    renderWithIntl(<InviteLinksPanel competitionId="c1" visibility="private" />);
    fireEvent.click(screen.getByRole("button", { name: "New link" }));
    expect(
      screen.queryByRole("option", { name: "View" }),
    ).not.toBeInTheDocument();
  });

  it("explains the view link's public-scoreboard dependency when selected", () => {
    renderWithIntl(<InviteLinksPanel competitionId="c1" visibility="public" />);
    fireEvent.click(screen.getByRole("button", { name: "New link" }));
    const select = screen.getByLabelText("Link type");
    fireEvent.change(select, { target: { value: "view" } });
    expect(
      screen.getByText(/public scoreboard is enabled/i),
    ).toBeInTheDocument();
  });

  it("renders rows with uses, status, and copies the landing URL", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    mockLinks = [makeLink({ max_uses: 10 })];
    renderWithIntl(<InviteLinksPanel competitionId="c1" visibility="private" />);

    expect(screen.getByText("sponsor email")).toBeInTheDocument();
    expect(screen.getByText("3 / 10")).toBeInTheDocument();
    // "Never" twice: the no-expiry column and the never-used column.
    expect(screen.getAllByText("Never")).toHaveLength(2);
    expect(screen.getByText("Active")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        expect.stringMatching(/\/invite\/tok123$/),
      ),
    );
  });

  it("revokes through the confirm dialog and hides actions on dead links", async () => {
    mockLinks = [makeLink()];
    renderWithIntl(<InviteLinksPanel competitionId="c1" visibility="private" />);
    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(mockRevoke).toHaveBeenCalledTimes(1));
    expect(mockRevoke.mock.calls[0][0]).toBe("l1");
  });

  it("shows a revoked link without copy or revoke actions", () => {
    mockLinks = [
      makeLink({ active: false, revoked_at: "2026-10-13T10:00:00Z" }),
    ];
    renderWithIntl(<InviteLinksPanel competitionId="c1" visibility="private" />);
    expect(screen.getByText("Revoked")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy link" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Revoke" })).toBeNull();
  });
});
