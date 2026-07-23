"use client";

import { use } from "react";

import { PoweredByFooter } from "@/components/app/powered-by-footer";
import { Lockup } from "@/components/brand/flagpost-mark";
import { Badge } from "@/components/ui/badge";
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
import { FALLBACK_SETTINGS, useSiteSettings } from "@/lib/hooks/use-site-settings";
import { usePublicScoreboard } from "@/lib/hooks/use-public-scoreboard";

// The standalone spectator scoreboard (no login) for a public competition.
// Lives outside the (app) shell so it needs no account; brand comes from the
// public site settings, attribution from the mandatory footer.
export default function PublicScoreboardPage({
  params,
}: {
  params: Promise<{ competitionId: string }>;
}) {
  const { competitionId } = use(params);
  const { data, isLoading, isError } = usePublicScoreboard(competitionId);
  const { data: settings } = useSiteSettings();
  const brand = settings ?? FALLBACK_SETTINGS;

  return (
    <div className="mx-auto flex min-h-dvh max-w-3xl flex-col gap-6 px-4 py-8">
      <header className="flex items-center justify-between gap-3">
        <Lockup
          size={32}
          label={brand.platform_name}
          logoUrl={brand.logo_url}
          showWordmark={brand.show_wordmark}
        />
        {data?.frozen && <Badge variant="secondary">Frozen</Badge>}
      </header>

      {isLoading && <Skeleton className="h-64 w-full" />}
      {isError && (
        <Card>
          <CardContent className="p-8 text-center text-sm text-muted-foreground">
            This scoreboard isn&apos;t public, or the competition doesn&apos;t exist.
          </CardContent>
        </Card>
      )}

      {data && (
        <>
          <div>
            <h1 className="text-2xl font-semibold">{data.name}</h1>
            <p className="text-sm text-muted-foreground">
              {data.mode === "team" ? "Team" : "Individual"} scoreboard
              {data.frozen && " · frozen"}
            </p>
          </div>

          {data.entries.length === 0 ? (
            <Card>
              <CardContent className="p-8 text-center text-sm text-muted-foreground">
                No scores yet — the board fills in on the first solve.
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="pt-2">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-12">Rank</TableHead>
                      <TableHead>{data.mode === "team" ? "Team" : "Competitor"}</TableHead>
                      <TableHead className="text-right">Points</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.entries.map((e) => (
                      <TableRow key={e.subject_id}>
                        <TableCell className="font-mono text-muted-foreground">
                          {e.rank}
                        </TableCell>
                        <TableCell className="font-medium">{e.name}</TableCell>
                        <TableCell className="text-right font-mono">{e.points}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </>
      )}

      <PoweredByFooter className="mt-auto" />
    </div>
  );
}
