"use client";

// Dashboard widgets (§10.1). Each is self-contained: it fetches its own data
// via domain hooks and renders inside whatever grid cell the layout gives it —
// it never assumes a position or an adjacent widget.

import Link from "next/link";
import { useTranslations } from "next-intl";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { severityStyle } from "@/lib/announcement-severity";
import { cn } from "@/lib/utils";
import { useRelativeTime } from "@/lib/hooks/use-relative-time";
import { useAnnouncements } from "@/lib/hooks/use-announcements";
import { useChallenges } from "@/lib/hooks/use-challenges";
import { useCompetition } from "@/lib/hooks/use-competitions";
import {
  useChallengeHealth,
  useDashboardStats,
  useMyStanding,
  useRecentSolves,
} from "@/lib/hooks/use-dashboard";
import { useSupportQueueLive, useTickets } from "@/lib/hooks/use-tickets";

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
      {/* min-h-0 lets this flex child shrink below its content so the grid cell's
          height governs and the body scrolls internally; it grows to fill a
          taller cell (issue #21 free resize). */}
      <CardContent className="min-h-0 flex-1 overflow-y-auto">{children}</CardContent>
    </Card>
  );
}

export function StatsWidget({ competitionId }: WidgetProps) {
  const t = useTranslations("dashboard.stats");
  const stats = useDashboardStats(competitionId);
  const competition = useCompetition(competitionId);
  const isTeam = competition.data?.participation_mode !== "individual";

  if (stats.isLoading) return <Skeleton className="h-24 w-full" />;
  const s = stats.data;

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <StatTile label={t("solves")} value={s?.total_solves ?? "—"} />
      <StatTile label={t("submissions")} value={s?.total_submissions ?? "—"} />
      <StatTile
        label={isTeam ? t("activeTeams") : t("activeParticipants")}
        value={s?.active_participants ?? "—"}
      />
      <StatTile label={t("publishedChallenges")} value={s?.published_challenges ?? "—"} />
    </div>
  );
}

export function StandingWidget({ competitionId }: WidgetProps) {
  const t = useTranslations("dashboard.standing");
  const standing = useMyStanding(competitionId);
  if (standing.isLoading) return <Skeleton className="h-24 w-full" />;
  const s = standing.data;
  return (
    <div className="grid grid-cols-3 gap-4">
      <StatTile label={t("rank")} value={s?.rank != null ? `#${s.rank}` : "—"} />
      <StatTile label={t("points")} value={s?.points ?? 0} />
      <StatTile label={t("solved")} value={s?.solved_count ?? 0} />
    </div>
  );
}

export function ActivityWidget({ competitionId }: WidgetProps) {
  const t = useTranslations("dashboard.activity");
  const rel = useRelativeTime();
  const solves = useRecentSolves(competitionId);
  return (
    <ListCard title={t("title")} description={t("description")}>
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
                {t.rich("line", {
                  name: ev.subject_name,
                  challenge: ev.challenge_title,
                  points: ev.points,
                  b: (chunks) => <span className="font-medium">{chunks}</span>,
                  c: (chunks) => <span className="text-muted-foreground">{chunks}</span>,
                  p: (chunks) => <span className="font-mono text-primary">{chunks}</span>,
                })}
              </span>
              <span className="whitespace-nowrap text-xs text-muted-foreground">
                {rel(ev.at)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">{t("empty")}</p>
      )}
    </ListCard>
  );
}

export function AnnouncementsWidget({ competitionId }: WidgetProps) {
  const t = useTranslations("dashboard.announcements");
  const ts = useTranslations("announcements");
  const rel = useRelativeTime();
  // The shell banner already holds this competition's announcements socket;
  // read from the shared cache rather than opening a second (§8).
  const announcements = useAnnouncements(competitionId, { subscribe: false });
  return (
    <ListCard title={t("title")} description={t("description")}>
      {announcements.data && announcements.data.length > 0 ? (
        <ul className="grid gap-3">
          {announcements.data.map((an) => {
            const style = severityStyle(an.severity);
            return (
              <li key={an.id} className="grid gap-0.5">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-[13px] font-medium">{an.title}</span>
                  <span className="whitespace-nowrap text-[11px] text-muted-foreground">
                    {rel(an.created_at)}
                  </span>
                </div>
                {/* Only flag the elevated rungs — chipping every routine
                    announcement would just add noise. */}
                {an.severity !== "info" && (
                  <span
                    className={cn(
                      "w-fit rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                      style.chip,
                    )}
                  >
                    {ts(`severity.${style.key}`)}
                  </span>
                )}
                <span className="text-[13px] text-muted-foreground">{an.body}</span>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">{t("empty")}</p>
      )}
    </ListCard>
  );
}

export function ChallengeHealthWidget({ competitionId }: WidgetProps) {
  const t = useTranslations("dashboard.health");
  const health = useChallengeHealth(competitionId, true);
  return (
    <ListCard title={t("title")} description={t("description")}>
      {health.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : health.data && health.data.length > 0 ? (
        <ul className="grid gap-2">
          {health.data.map((c) => (
            <li key={c.challenge_id} className="flex items-center justify-between gap-3 text-sm">
              <span className="min-w-0 truncate">{c.title}</span>
              <span className="whitespace-nowrap font-mono text-xs text-muted-foreground">
                {t("stat", { solves: c.solves, attempts: c.attempts })}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">{t("empty")}</p>
      )}
    </ListCard>
  );
}

export function SupportQueueWidget({ competitionId }: WidgetProps) {
  const t = useTranslations("dashboard.support");
  // Staff widget: the live open-ticket queue. Subscribing here keeps the count
  // fresh and plays the §4.4 cue when a new ticket arrives while on the dashboard.
  useSupportQueueLive(competitionId, true);
  const tickets = useTickets(competitionId, "open");
  const open = tickets.data ?? [];
  return (
    <ListCard title={t("title")} description={t("open", { count: open.length })}>
      {tickets.isLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : open.length > 0 ? (
        <ul className="grid gap-2">
          {open.map((t) => (
            <li key={t.id} className="flex items-center justify-between gap-3 text-sm">
              <span className="min-w-0 truncate">{t.subject}</span>
              <span className="whitespace-nowrap text-xs text-muted-foreground">
                {t.team_name ?? t.opener_name}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">
          {t("emptyPrefix")}{" "}
          <Link href="/support" className="text-primary hover:underline">{t("emptyLink")}</Link>
        </p>
      )}
    </ListCard>
  );
}

export function MySolvesWidget({ competitionId }: WidgetProps) {
  const t = useTranslations("dashboard.mySolves");
  const challenges = useChallenges(competitionId);
  const solved = (challenges.data ?? []).filter((c) => c.solved);
  return (
    <ListCard title={t("title")} description={t("solved", { count: solved.length })}>
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
        <p className="text-sm text-muted-foreground">{t("empty")}</p>
      )}
    </ListCard>
  );
}
