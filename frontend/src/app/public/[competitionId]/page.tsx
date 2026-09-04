"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, use } from "react";

import { LocaleSwitcher } from "@/components/app/locale-switcher";
import { PoweredByFooter } from "@/components/app/powered-by-footer";
import { Lockup } from "@/components/brand/flagpost-mark";
import { StatTiles, Highlights } from "@/components/public/insights-cards";
import { PointsTimeline } from "@/components/public/points-timeline";
import { VenueMode } from "@/components/public/venue/venue-mode";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useBrandSettings } from "@/lib/hooks/use-site-settings";
import {
  usePublicActivity,
  usePublicInsights,
  usePublicScoreboard,
} from "@/lib/hooks/use-public-scoreboard";
import { parseRotateSeconds } from "@/lib/venue";

// The standalone spectator scoreboard (no login) for a public competition.
// Lives outside the (app) shell so it needs no account; brand comes from the
// public site settings, attribution from the mandatory footer. Wider than the
// app's own pages (#24) because the points timeline wants the room.
//
// Venue mode (#77) is an in-page toggle: `?venue=1` swaps the static view for a
// full-screen rotating display, kept in the URL so it's bookmarkable and
// survives a refresh. `?interval=` tunes the rotation cadence.
export default function PublicScoreboardPage({
  params,
}: {
  params: Promise<{ competitionId: string }>;
}) {
  // Split so useSearchParams sits under a Suspense boundary — without one Next
  // refuses to prerender the route (a build-time contract, not a nicety).
  return (
    <Suspense fallback={<PublicScoreboardFallback />}>
      <PublicScoreboardContent params={params} />
    </Suspense>
  );
}

function PublicScoreboardFallback() {
  return (
    <div className="mx-auto flex min-h-dvh max-w-7xl flex-col gap-6 px-4 py-8">
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

function PublicScoreboardContent({
  params,
}: {
  params: Promise<{ competitionId: string }>;
}) {
  const t = useTranslations("scoreboard.public");
  const { competitionId } = use(params);
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const venue = searchParams.get("venue") === "1";
  const intervalSeconds = parseRotateSeconds(searchParams.get("interval"));

  const { data, isLoading, isError } = usePublicScoreboard(competitionId);
  // Insights are a separate fetch: richer, and if it fails the standings — the
  // thing people came for — still render.
  const { data: insights } = usePublicInsights(competitionId);
  // Recent-solves feed drives venue mode's first-blood splash; only polled while
  // venue mode is on, so the static page adds no extra request load.
  const { data: activity } = usePublicActivity(competitionId, { enabled: venue });
  const brand = useBrandSettings();

  const enterVenue = () => {
    router.replace(`${pathname}?venue=1`);
    document.documentElement.requestFullscreen?.().catch(() => {});
  };
  const exitVenue = () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    router.replace(pathname);
  };

  if (venue && data) {
    return (
      <VenueMode
        scoreboard={data}
        insights={insights}
        activity={activity}
        brand={brand}
        intervalSeconds={intervalSeconds}
        onExit={exitVenue}
      />
    );
  }

  return (
    <div className="mx-auto flex min-h-dvh max-w-7xl flex-col gap-6 px-4 py-8">
      <header className="flex items-center justify-between gap-3">
        <Lockup
          size={32}
          label={brand.platform_name}
          logoUrl={brand.logo_url}
          showWordmark={brand.show_wordmark}
        />
        <div className="flex items-center gap-2">
          {data?.frozen && <Badge variant="secondary">{t("frozen")}</Badge>}
          {data && (
            <Button variant="outline" size="sm" onClick={enterVenue}>
              {t("venueMode")}
            </Button>
          )}
        </div>
      </header>

      {isLoading && <Skeleton className="h-64 w-full" />}
      {isError && (
        <Card>
          <CardContent className="p-8 text-center text-sm text-muted-foreground">
            {t("notPublic")}
          </CardContent>
        </Card>
      )}

      {data && (
        <>
          <div>
            <Link href="/public" className="text-xs text-primary underline">
              {t("backToAll")}
            </Link>
            <h1 className="mt-1 text-2xl font-semibold">{data.name}</h1>
            <p className="text-sm text-muted-foreground">
              {data.mode === "team" ? t("teamScoreboard") : t("individualScoreboard")}
              {data.frozen && ` ${t("frozenSuffix")}`}
            </p>
          </div>

          {insights && <StatTiles stats={insights.stats} />}

          {insights && (
            <PointsTimeline
              series={insights.timeline.series}
              start={insights.timeline.start}
              end={insights.timeline.end}
              frozen={insights.frozen}
            />
          )}

          {data.entries.length === 0 ? (
            <Card>
              <CardContent className="p-8 text-center text-sm text-muted-foreground">
                {t("emptyBoard")}
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-4 lg:grid-cols-3">
              <Card className="lg:col-span-2">
                <CardContent className="pt-2">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-12">{t("rank")}</TableHead>
                        <TableHead>
                          {data.mode === "team" ? t("team") : t("competitor")}
                        </TableHead>
                        <TableHead className="text-right">{t("points")}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.entries.map((e) => (
                        <TableRow key={e.subject_id}>
                          <TableCell className="font-mono text-muted-foreground">
                            {e.rank}
                          </TableCell>
                          <TableCell className="font-medium">{e.name}</TableCell>
                          <TableCell className="text-right font-mono">
                            {e.points}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>

              {insights && <Highlights highlights={insights.highlights} />}
            </div>
          )}
        </>
      )}

      <div className="mt-auto flex flex-col items-center">
        <LocaleSwitcher />
        <PoweredByFooter />
      </div>
    </div>
  );
}
