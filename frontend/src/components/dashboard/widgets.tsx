"use client";

// Dashboard widgets (§10.1). Each is self-contained: it fetches its own data
// via domain hooks and renders inside whatever grid cell the layout gives it —
// it never assumes a position or an adjacent widget.

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { relativeTime } from "@/lib/datetime";
import { useAnnouncements } from "@/lib/hooks/use-announcements";
import { useChallenges } from "@/lib/hooks/use-challenges";
import { useCompetition } from "@/lib/hooks/use-competitions";
import {
  useChallengeHealth,
  useDashboardStats,
  useMyStanding,
  useRecentSolves,
} from "@/lib/hooks/use-dashboard";

type WidgetProps = { competitionId: string };

function StatTile({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-border bg-card p-4 text-center">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 font-display text-2xl font-semibold tracking-tight">{value}</div>
    </div>
  );
}

/** A card that fills its grid cell, with an internally-scrolling body. */
function ListCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="flex h-full flex-col">
      <CardHeader className="flex-shrink-0">
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent className="max-h-72 flex-1 overflow-y-auto">{children}</CardContent>
    </Card>
  );
}

export function StatsWidget({ competitionId }: WidgetProps) {
  const stats = useDashboardStats(competitionId);
  const competition = useCompetition(competitionId);
  const isTeam = competition.data?.participation_mode !== "individual";

  if (stats.isLoading) return <Skeleton className="h-24 w-full" />;
  const s = stats.data;

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <StatTile label="Solves" value={s?.total_solves ?? "—"} />
      <StatTile label="Submissions" value={s?.total_submissions ?? "—"} />
      <StatTile
        label={isTeam ? "Active teams" : "Active participants"}
        value={s?.active_participants ?? "—"}
      />
      <StatTile label="Published challenges" value={s?.published_challenges ?? "—"} />
    </div>
  );
}

export function StandingWidget({ competitionId }: WidgetProps) {
  const standing = useMyStanding(competitionId);
  if (standing.isLoading) return <Skeleton className="h-24 w-full" />;
  const s = standing.data;
  return (
    <div className="grid grid-cols-3 gap-4">
      <StatTile label="Your rank" value={s?.rank != null ? `#${s.rank}` : "—"} />
      <StatTile label="Your points" value={s?.points ?? 0} />
      <StatTile label="Solved" value={s?.solved_count ?? 0} />
    </div>
  );
}

export function ActivityWidget({ competitionId }: WidgetProps) {
  const solves = useRecentSolves(competitionId);
  return (
    <ListCard title="Recent activity" description="Latest solves across the competition">
      {solves.isLoading ? (
        <div className="grid gap-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
        </div>
      ) : solves.data && solves.data.length > 0 ? (
        <ul className="grid gap-3">
          {solves.data.map((ev, i) => (
            <li key={i} className="flex items-baseline justify-between gap-3 text-sm">
              <span className="min-w-0">
                <span className="font-medium">{ev.subject_name}</span> solved{" "}
                <span className="text-muted-foreground">{ev.challenge_title}</span>{" "}
                <span className="font-mono text-primary">+{ev.points}</span>
              </span>
              <span className="whitespace-nowrap text-xs text-muted-foreground">
                {relativeTime(ev.at)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">No solves yet.</p>
      )}
    </ListCard>
  );
}

export function AnnouncementsWidget({ competitionId }: WidgetProps) {
  // The shell banner already holds this competition's announcements socket;
  // read from the shared cache rather than opening a second (§8).
  const announcements = useAnnouncements(competitionId, { subscribe: false });
  return (
    <ListCard title="Announcements" description="Archive, newest first">
      {announcements.data && announcements.data.length > 0 ? (
        <ul className="grid gap-3">
          {announcements.data.map((an) => (
            <li key={an.id} className="grid gap-0.5">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[13px] font-medium">{an.title}</span>
                <span className="whitespace-nowrap text-[11px] text-muted-foreground">
                  {relativeTime(an.created_at)}
                </span>
              </div>
              <span className="text-[13px] text-muted-foreground">{an.body}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">No announcements yet.</p>
      )}
    </ListCard>
  );
}

export function ChallengeHealthWidget({ competitionId }: WidgetProps) {
  const health = useChallengeHealth(competitionId, true);
  return (
    <ListCard title="Challenge health" description="Solves vs. attempts">
      {health.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : health.data && health.data.length > 0 ? (
        <ul className="grid gap-2">
          {health.data.map((c) => (
            <li key={c.challenge_id} className="flex items-center justify-between gap-3 text-sm">
              <span className="min-w-0 truncate">{c.title}</span>
              <span className="whitespace-nowrap font-mono text-xs text-muted-foreground">
                {c.solves} solved · {c.attempts} tries
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">No challenges yet.</p>
      )}
    </ListCard>
  );
}

export function MySolvesWidget({ competitionId }: WidgetProps) {
  const challenges = useChallenges(competitionId);
  const solved = (challenges.data ?? []).filter((c) => c.solved);
  return (
    <ListCard title="Your solves" description={`${solved.length} solved`}>
      {challenges.isLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : solved.length > 0 ? (
        <ul className="grid gap-2">
          {solved.map((c) => (
            <li key={c.id} className="flex items-center justify-between gap-3 text-sm">
              <span className="min-w-0 truncate">{c.title}</span>
              <span className="whitespace-nowrap font-mono text-primary">+{c.points}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">
          No solves yet — head to Challenges to get started.
        </p>
      )}
    </ListCard>
  );
}
