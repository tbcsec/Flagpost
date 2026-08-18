import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import CompetitionSettingsPage from "@/app/(app)/settings/page";
import type { Competition } from "@/lib/types";

// The page + real CompetitionSettingsForm render against a mocked hook layer;
// the heavy always-mounted siblings (they live in hidden divs, not conditional
// renders) are stubbed out.
let active: {
  competitionId: string | null;
  data: Competition | null;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
};

vi.mock("@/lib/hooks/use-competitions", () => ({
  useActiveCompetition: () => active,
  useUpdateCompetition: () => ({ mutate: vi.fn(), isPending: false }),
  useSetCompetitionStatus: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/lib/hooks/use-scoreboard", () => ({
  useFreezeScoreboard: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/lib/hooks/use-permissions", () => ({
  useAccess: () => ({ has: () => false }),
}));
vi.mock("@/lib/hooks/use-modules", () => ({
  useEnabledModules: () => ({ data: [] }),
}));
vi.mock("@/components/challenges/challenge-admin", () => ({
  CategoryManager: () => null,
}));
vi.mock("@/components/competitions/modules-panel", () => ({
  ModulesPanel: () => null,
}));
vi.mock("@/components/ui/rich-text-editor", () => ({
  RichTextEditor: () => null,
}));
vi.mock("@/components/ui/confirm", () => ({
  useConfirm: () => () => Promise.resolve(true),
}));
vi.mock("@/stores/toast", () => ({ toast: vi.fn() }));

function makeCompetition(overrides: Partial<Competition>): Competition {
  return {
    id: "c1",
    name: "Alpha CTF",
    description: "",
    participation_mode: "team",
    visibility: "private",
    status: "running",
    start_at: null,
    end_at: null,
    registration_opens_at: null,
    registration_closes_at: null,
    mc_guess_limit: 2,
    mc_penalty_pct: null,
    challenge_ratings_enabled: false,
    challenge_tags: [],
    difficulty_tiers: [],
    public_scoreboard: false,
    ctftime_enabled: false,
    brackets: [],
    max_team_size: null,
    rules_override: null,
    rules_display_only: false,
    ...overrides,
  } as Competition;
}

function setActive(id: string, name: string) {
  active = {
    competitionId: id,
    data: makeCompetition({ id, name }),
    isLoading: false,
    isError: false,
    error: null,
  };
}

describe("CompetitionSettingsPage across competition switches (#258)", () => {
  it("drops unsaved edits when the active competition changes", () => {
    setActive("c1", "Alpha CTF");
    const { rerender } = renderWithIntl(<CompetitionSettingsPage />);

    const name = screen.getByLabelText("Name");
    expect(name).toHaveValue("Alpha CTF");
    fireEvent.change(name, { target: { value: "Unsaved edit" } });
    expect(name).toHaveValue("Unsaved edit");

    // The switcher changes the active competition: the keyed content remounts
    // and every field re-derives from the new competition — competition A's
    // draft must NOT survive into B (Save would write it across tenants).
    setActive("c2", "Beta CTF");
    rerender(<CompetitionSettingsPage />);
    expect(screen.getByLabelText("Name")).toHaveValue("Beta CTF");
  });

  it("keeps unsaved edits across a tab switch within one competition", () => {
    // The existing deliberate contract (the form stays mounted, just hidden):
    // the competition key must not break it.
    setActive("c1", "Alpha CTF");
    renderWithIntl(<CompetitionSettingsPage />);

    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Unsaved edit" },
    });
    fireEvent.click(screen.getByRole("tab", { name: "Controls" }));
    fireEvent.click(screen.getByRole("tab", { name: "General" }));
    expect(screen.getByLabelText("Name")).toHaveValue("Unsaved edit");
  });
});
