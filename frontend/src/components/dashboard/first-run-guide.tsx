"use client";

// First-run onboarding for managers (ROADMAP #24). On a brand-new competition —
// no published challenges yet — the operational dashboard would otherwise be a
// wall of zeroes, so this points at the concrete next steps instead. It fetches
// the same dashboard stats the widgets do (TanStack dedupes the query) and
// disappears the moment the first challenge is published.

import Link from "next/link";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useDashboardStats } from "@/lib/hooks/use-dashboard";

const STEPS = [
  {
    href: "/challenges",
    title: "Create challenges",
    description: "Add and publish your first challenges so competitors have something to solve.",
  },
  {
    href: "/participants",
    title: "Invite teams",
    description: "Share the join link or invite code so players can register and form teams.",
  },
  {
    href: "/admin/settings",
    title: "Brand your event",
    description:
      "Set the platform name, palette, and accent under Admin → Site settings → Appearance.",
  },
];

export function FirstRunGuide({ competitionId }: { competitionId: string }) {
  const stats = useDashboardStats(competitionId);
  // Only while the competition is genuinely empty; gone once anything is live.
  if (!stats.data || stats.data.published_challenges > 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Getting started</CardTitle>
      </CardHeader>
      <CardContent>
        <ol className="grid gap-2.5">
          {STEPS.map((step, i) => (
            <li key={step.href}>
              <Link
                href={step.href}
                className="flex items-start gap-3 rounded-md border border-border p-3 transition-colors hover:border-primary/40 hover:bg-accent/40"
              >
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 font-mono text-xs font-semibold text-primary">
                  {i + 1}
                </span>
                <span className="grid gap-0.5">
                  <span className="text-sm font-medium">{step.title}</span>
                  <span className="text-xs text-muted-foreground">{step.description}</span>
                </span>
              </Link>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
