import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { ChallengeAdmin } from "@/components/challenges/challenge-admin";
import type { Challenge } from "@/lib/types";

// The authoring form seeds every field from props via useState initializers,
// which only run on mount — so the form must be keyed per edit target. Without
// that key the previous challenge's values persist into the next one and are
// SAVED onto it (#262 review; same bug class as #258/#260 on the settings page).
// The master-detail redesign keeps that guarantee: selecting a different list
// item, or switching to "New", remounts the editor.

function mk(partial: Partial<Challenge> & { id: string; title: string }): Challenge {
  return {
    competition_id: "c-1",
    description: {},
    category_id: null,
    points: 100,
    scoring_type: "static",
    min_points: null,
    decay: null,
    value: 100,
    release_at: null,
    prerequisites: [],
    locked: false,
    tags: [],
    difficulty: null,
    connection_info: null,
    state: "published",
    flag_type: "static",
    case_insensitive: false,
    has_flag: true,
    choices: null,
    attempts_remaining: null,
    subject_value: null,
    my_rating: null,
    solved: false,
    solve_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    ...partial,
  };
}

const ALPHA = mk({
  id: "a",
  title: "Alpha",
  connection_info: "nc secret.example.com 1337",
});
const BRAVO = mk({ id: "b", title: "Bravo", connection_info: null });

const createMutate = vi.fn();
const updateMutate = vi.fn();
const updateIds: string[] = [];

vi.mock("@/lib/hooks/use-challenges", () => ({
  useChallenges: () => ({ data: [ALPHA, BRAVO], isLoading: false, isError: false }),
  useCreateChallenge: () => ({ mutate: createMutate, isPending: false }),
  useUpdateChallenge: (_c: string, id: string) => {
    updateIds.push(id);
    return { mutate: updateMutate, isPending: false };
  },
  useChallengeStateMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useExportChallenges: () => ({ mutate: vi.fn(), isPending: false }),
  useImportChallenges: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/lib/hooks/use-categories", () => ({
  useCategories: () => ({ data: [] }),
  useCreateCategory: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteCategory: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/lib/hooks/use-competitions", () => ({
  useActiveCompetition: () => ({ data: { difficulty_tiers: [], challenge_tags: [] } }),
}));
vi.mock("@/components/ui/confirm", () => ({ useConfirm: () => () => Promise.resolve(true) }));
vi.mock("@/components/ui/rich-text-editor", () => ({ RichTextEditor: () => null }));
vi.mock("@/components/challenges/attachments-section", () => ({ AttachmentsSection: () => null }));
vi.mock("@/components/challenges/hints-section", () => ({ HintsSection: () => null }));
vi.mock("@/components/challenges/challenge-guesses-section", () => ({
  ChallengeGuessesSection: () => null,
}));
vi.mock("@/components/challenges/deployment-section", () => ({
  DeploymentSection: () => null,
}));
vi.mock("@/stores/toast", () => ({ toast: vi.fn() }));

afterEach(() => {
  createMutate.mockClear();
  updateMutate.mockClear();
  updateIds.length = 0;
});

// Click the list row for `title`. Rows are buttons inside the list <ul>; the
// editor header renders the same title as an <h2>, so scope to the list to avoid
// selecting that instead.
function selectItem(title: string) {
  const row = screen
    .getAllByRole("button")
    .find((b) => b.closest("ul") !== null && b.textContent?.includes(title));
  if (!row) throw new Error(`no list row for ${title}`);
  fireEvent.click(row);
}

describe("ChallengeAdmin master-detail editor", () => {
  it("shows the select prompt until a challenge is chosen", () => {
    renderWithIntl(<ChallengeAdmin competitionId="c-1" />);
    // No editor yet — the right pane prompts you to pick something.
    expect(screen.queryByLabelText("Title")).toBeNull();

    selectItem("Alpha");
    expect(screen.getByLabelText("Title")).toHaveValue("Alpha");
  });

  it("does not carry a challenge's values into a new challenge", () => {
    renderWithIntl(<ChallengeAdmin competitionId="c-1" />);
    selectItem("Alpha");
    expect(screen.getByLabelText("Title")).toHaveValue("Alpha");
    expect(screen.getByLabelText("Connection info")).toHaveValue(
      "nc secret.example.com 1337",
    );

    // Switch to creating a new challenge: the form must be blank, not Alpha's.
    fireEvent.click(screen.getByRole("button", { name: "New challenge" }));
    expect(screen.getByLabelText("Title")).toHaveValue("");
    expect(screen.getByLabelText("Connection info")).toHaveValue("");
  });

  it("does not save one challenge's values onto another when switching targets", () => {
    renderWithIntl(<ChallengeAdmin competitionId="c-1" />);
    selectItem("Alpha");
    selectItem("Bravo");

    // Bravo's own values, not Alpha's — otherwise saving would overwrite them.
    expect(screen.getByLabelText("Title")).toHaveValue("Bravo");
    expect(screen.getByLabelText("Connection info")).toHaveValue("");
    // The mutation is bound to the challenge actually being edited.
    expect(updateIds[updateIds.length - 1]).toBe("b");
  });
});
