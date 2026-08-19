import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ChallengeList,
  groupChallengesByCategory,
} from "@/components/challenges/challenge-list";
import { renderWithIntl } from "@/test/intl";
import type { Challenge } from "@/lib/types";
import { useChallengeViewStore } from "@/stores/challenge-view";

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

const CATEGORIES = [
  { id: "web", name: "web" },
  { id: "crypto", name: "crypto" },
  { id: "empty", name: "empty" },
];

describe("groupChallengesByCategory", () => {
  it("groups into non-empty categories in the categories order, with counts", () => {
    const challenges = [
      mk({ id: "1", title: "A", category_id: "crypto", solved: true }),
      mk({ id: "2", title: "B", category_id: "web" }),
      mk({ id: "3", title: "C", category_id: "web", solved: true }),
    ];
    const groups = groupChallengesByCategory(challenges, CATEGORIES);
    // "empty" is skipped; "web" precedes "crypto" (categories order).
    expect(groups.map((g) => g.id)).toEqual(["web", "crypto"]);
    const web = groups[0];
    expect(web.total).toBe(2);
    expect(web.solved).toBe(1);
  });

  it("folds null and unknown-category challenges into a trailing uncategorized group", () => {
    const challenges = [
      mk({ id: "1", title: "A", category_id: "web" }),
      mk({ id: "2", title: "B", category_id: null }),
      mk({ id: "3", title: "C", category_id: "deleted-cat" }),
    ];
    const groups = groupChallengesByCategory(challenges, CATEGORIES);
    expect(groups.map((g) => g.id)).toEqual(["web", ""]);
    const uncategorized = groups[groups.length - 1];
    expect(uncategorized.name).toBe("uncategorized");
    expect(uncategorized.challenges.map((c) => c.id)).toEqual(["2", "3"]);
  });

  it("returns nothing when there are no challenges", () => {
    expect(groupChallengesByCategory([], CATEGORIES)).toEqual([]);
  });
});

describe("ChallengeList", () => {
  beforeEach(() => {
    useChallengeViewStore.setState({ viewMode: "list", expanded: [] });
  });

  const challenges = [
    mk({ id: "1", title: "SQL injection 101", category_id: "web", difficulty: "easy", value: 50, solve_count: 142, solved: true }),
    mk({ id: "2", title: "Deserial killer", category_id: "web", difficulty: "hard", value: 400, solve_count: 3, locked: true }),
  ];

  it("renders category sections collapsed by default (rows hidden)", () => {
    renderWithIntl(<ChallengeList challenges={challenges} categories={CATEGORIES} onOpen={vi.fn()} />);
    // The category header and its count show...
    expect(screen.getByRole("button", { name: /web/i })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("1/2")).toBeInTheDocument();
    // ...but the rows are not rendered while collapsed.
    expect(screen.queryByText("SQL injection 101")).not.toBeInTheDocument();
  });

  it("expands a category on click and shows rows with points, difficulty, and solve count", () => {
    renderWithIntl(<ChallengeList challenges={challenges} categories={CATEGORIES} onOpen={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /web/i }));

    expect(screen.getByText("SQL injection 101")).toBeInTheDocument();
    expect(screen.getByText(/50\s*pts/)).toBeInTheDocument();
    expect(screen.getByText("easy")).toBeInTheDocument();
    expect(screen.getByText("142 solves")).toBeInTheDocument();
  });

  it("marks a locked row with a padlock and a solved row with an sr-only label", () => {
    useChallengeViewStore.setState({ viewMode: "list", expanded: ["web"] });
    renderWithIntl(<ChallengeList challenges={challenges} categories={CATEGORIES} onOpen={vi.fn()} />);
    expect(screen.getByRole("img", { name: "Locked" })).toBeInTheDocument();
    expect(screen.getByText("Solved")).toBeInTheDocument();
  });

  it("opens the challenge when its row is clicked", () => {
    const onOpen = vi.fn();
    useChallengeViewStore.setState({ viewMode: "list", expanded: ["web"] });
    renderWithIntl(<ChallengeList challenges={challenges} categories={CATEGORIES} onOpen={onOpen} />);
    fireEvent.click(screen.getByText("SQL injection 101"));
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: "1" }));
  });

  it("shows an empty-filter message when nothing matches", () => {
    renderWithIntl(<ChallengeList challenges={[]} categories={CATEGORIES} onOpen={vi.fn()} />);
    expect(screen.getByText(/no challenges match this filter/i)).toBeInTheDocument();
  });

  it("shows the reduced subject value with the base struck through (#148)", () => {
    useChallengeViewStore.setState({ viewMode: "list", expanded: ["web"] });
    renderWithIntl(
      <ChallengeList
        challenges={[
          mk({ id: "3", title: "Quiz", category_id: "web", value: 200, subject_value: 150 }),
        ]}
        categories={CATEGORIES}
        onOpen={vi.fn()}
      />,
    );
    // The live worth for the subject is 150 pts...
    expect(screen.getByText(/150\s*pts/)).toBeInTheDocument();
    // ...with the base value struck through beside it.
    const base = screen.getByText("200");
    expect(base).toHaveClass("line-through");
  });
});
