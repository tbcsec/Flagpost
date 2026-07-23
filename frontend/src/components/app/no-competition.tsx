"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { EmptyState, TrophyEmptyIcon } from "@/components/ui/empty-state";
import { useAccess } from "@/lib/hooks/use-permissions";

// Shown on competition-scoped surfaces when there's no active competition — a
// fresh install has none until an admin creates one. Role-aware: staff get a
// create CTA, everyone else gets a reassuring "check back" message.
export function NoCompetition() {
  const access = useAccess();
  const canCreate = access.has("create_competition");
  return (
    <EmptyState
      icon={<TrophyEmptyIcon />}
      title="No competition loaded"
      description={
        canCreate
          ? "There aren't any competitions yet. Create one to open its challenges, teams, scoreboard, and more."
          : "There aren't any competitions available to you yet. Check back soon."
      }
      action={
        canCreate ? (
          <Button asChild>
            <Link href="/admin/competitions">Manage competitions</Link>
          </Button>
        ) : undefined
      }
    />
  );
}
