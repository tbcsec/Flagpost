"use client";

import { useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import { ChallengeValue } from "@/components/challenges/challenge-value";
import type { Challenge } from "@/lib/types";
import { useChallengeViewStore } from "@/stores/challenge-view";
import { cn } from "@/lib/utils";

// The alternative "list" presentation for the challenges page (#55): challenges
// grouped by category into collapsible sections (collapsed by default), each row
// a compact line — name, difficulty, solve count, points — with a padlock on
// locked challenges. An opt-in alternative to the default card grid; the card
// grid stays the default. See ChallengesPage for the view toggle that selects it.

export interface ChallengeCategoryGroup {
  /** Category id, or "" for the synthetic "uncategorized" bucket. */
  id: string;
  name: string;
  challenges: Challenge[];
  solved: number;
  total: number;
}

/** Group an already-filtered challenge set into ordered, non-empty category
 *  sections. Pure so the grouping is unit-testable without rendering.
 *
 *  Group order follows `categories` (the same order the filter chips use), so
 *  the list reads consistently with the chip row. Challenges whose `category_id`
 *  is null — or points at a category not in the list — fold into a trailing
 *  "uncategorized" group, mirroring the card view's `categoryName` fallback. */
export function groupChallengesByCategory(
  challenges: Challenge[],
  categories: { id: string; name: string }[],
): ChallengeCategoryGroup[] {
  const groups: ChallengeCategoryGroup[] = [];
  for (const cat of categories) {
    const inCat = challenges.filter((c) => c.category_id === cat.id);
    if (inCat.length === 0) continue;
    groups.push({
      id: cat.id,
      name: cat.name,
      challenges: inCat,
      solved: inCat.filter((c) => c.solved).length,
      total: inCat.length,
    });
  }
  const known = new Set(categories.map((c) => c.id));
  const uncategorized = challenges.filter(
    (c) => c.category_id === null || !known.has(c.category_id),
  );
  if (uncategorized.length > 0) {
    groups.push({
      id: "",
      name: "uncategorized",
      challenges: uncategorized,
      solved: uncategorized.filter((c) => c.solved).length,
      total: uncategorized.length,
    });
  }
  return groups;
}

export function ChallengeList({
  challenges,
  categories,
  onOpen,
}: {
  challenges: Challenge[];
  categories: { id: string; name: string }[];
  onOpen: (challenge: Challenge) => void;
}) {
  const groups = useMemo(
    () => groupChallengesByCategory(challenges, categories),
    [challenges, categories],
  );

  if (groups.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No challenges match this filter.
      </p>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border">
      {groups.map((group) => (
        <ChallengeCategorySection
          key={group.id || "__uncategorized"}
          group={group}
          onOpen={onOpen}
        />
      ))}
    </div>
  );
}

function ChallengeCategorySection({
  group,
  onOpen,
}: {
  group: ChallengeCategoryGroup;
  onOpen: (challenge: Challenge) => void;
}) {
  // Expanded state is per-category and persisted (store-backed), collapsed by
  // default. Selecting a boolean keeps this row from re-rendering when an
  // unrelated category is toggled.
  const expanded = useChallengeViewStore((s) => s.expanded.includes(group.id));
  const toggleCategory = useChallengeViewStore((s) => s.toggleCategory);

  return (
    <section className="border-b border-border last:border-b-0">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => toggleCategory(group.id)}
        className="flex w-full items-center gap-2.5 px-4 py-3 text-left transition-colors hover:bg-accent/50"
      >
        <Chevron open={expanded} />
        <span className="font-medium capitalize">{group.name}</span>
        <span className="ml-auto font-mono text-xs text-muted-foreground">
          {group.solved}/{group.total}
        </span>
      </button>
      {expanded && (
        <ul className="border-t border-border">
          {group.challenges.map((ch) => (
            <ChallengeListRow key={ch.id} challenge={ch} onOpen={onOpen} />
          ))}
        </ul>
      )}
    </section>
  );
}

function ChallengeListRow({
  challenge: ch,
  onOpen,
}: {
  challenge: Challenge;
  onOpen: (challenge: Challenge) => void;
}) {
  const state = ch.locked ? "locked" : ch.solved ? "solved" : "open";
  return (
    <li className="border-t border-border first:border-t-0">
      <button
        type="button"
        onClick={() => onOpen(ch)}
        className={cn(
          "flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-accent/50",
          ch.solved && "bg-success/5",
        )}
      >
        <StatusMark state={state} />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="truncate text-sm font-medium">{ch.title}</span>
            {ch.state === "draft" && (
              <Badge variant="outline" className="text-[10px]">
                Draft
              </Badge>
            )}
          </span>
          <span className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
            {ch.difficulty && <span className="capitalize">{ch.difficulty}</span>}
            {ch.difficulty && <span aria-hidden="true">·</span>}
            <span>
              {ch.solve_count} solve{ch.solve_count === 1 ? "" : "s"}
            </span>
          </span>
        </span>
        <ChallengeValue challenge={ch} className="shrink-0 text-sm" />
      </button>
    </li>
  );
}

/** Leading state indicator. A locked challenge shows the padlock glyph the cards
 *  and detail dialog already use (a proper icon set is a separate, deferred
 *  change — issue comment); solved/open use a quiet colored dot with an sr-only
 *  label so the state isn't conveyed by colour alone. */
function StatusMark({ state }: { state: "solved" | "open" | "locked" }) {
  if (state === "locked") {
    return (
      <span className="shrink-0 text-sm leading-none" role="img" aria-label="Locked">
        🔒
      </span>
    );
  }
  return (
    <span className="flex shrink-0 items-center">
      <span
        aria-hidden="true"
        className={cn(
          "h-2 w-2 rounded-full",
          state === "solved" ? "bg-success" : "bg-muted-foreground/50",
        )}
      />
      <span className="sr-only">{state === "solved" ? "Solved" : "Open"}</span>
    </span>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn(
        "shrink-0 text-muted-foreground transition-transform",
        open && "rotate-90",
      )}
      aria-hidden="true"
    >
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}
