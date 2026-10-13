"use client";

// Profile → Skills: the caller's own cross-competition skills web (#364,
// ADR-0039) — a radar of their category strengths plus a ranked breakdown. The
// durable, cross-competition home, like the Certificates tab beside it.

import { useTranslations } from "next-intl";

import { SkillsRadar } from "@/components/skills/skills-radar";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useMySkills } from "@/lib/hooks/use-skills";
import { axisColor, radarMax } from "@/lib/skills-radar";

const BAR = axisColor(0); // hsl(var(--chart-1)) — same accent as the web

/** One stat tile, in the public insights-cards idiom (value on top, muted
 * label) — a bordered div rather than a nested Card since we're already inside
 * the profile card. */
function SkillStat({
  value,
  label,
  detail,
}: {
  value: string | number;
  label: string;
  detail?: number;
}) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div
        className="truncate text-base font-semibold capitalize tabular-nums"
        title={typeof value === "string" ? value : undefined}
      >
        {value}
        {detail !== undefined && (
          <span className="ml-1.5 font-mono text-xs font-normal text-muted-foreground">
            {detail}
          </span>
        )}
      </div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  );
}

export function MySkillsCard() {
  const t = useTranslations("profile.skills");
  const { data, isLoading, isError } = useMySkills();

  const scores = data?.skills ?? [];
  const max = radarMax(scores.map((s) => s.score));
  // At-a-glance stats (#436), derived client-side from the same payload. Sort a
  // copy — the API's order drives the radar axes and breakdown rows. "Least
  // solved" means the weakest *practised* category, and only reads as a fact
  // once there are two to compare.
  const ranked = [...scores].sort((a, b) => b.score - a.score);
  const strongest = ranked[0];
  const weakest = ranked.length >= 2 ? ranked[ranked.length - 1] : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-48 w-full" />
        ) : isError ? (
          <p role="alert" className="text-sm text-destructive">
            {t("loadError")}
          </p>
        ) : scores.length === 0 ? (
          <EmptyState title={t("emptyTitle")} description={t("emptyDescription")} />
        ) : (
          <div className="grid gap-6">
            {/* The stats strip (#436) — the summary line, promoted to tiles. */}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <SkillStat value={data?.total ?? 0} label={t("statTotal")} />
              <SkillStat
                value={data?.competitions_played ?? 0}
                label={t("statCompetitions")}
              />
              <SkillStat
                value={strongest.skill}
                detail={strongest.score}
                label={t("statStrongest")}
              />
              <SkillStat
                value={weakest ? weakest.skill : "—"}
                detail={weakest?.score}
                label={t("statWeakest")}
              />
            </div>
            {/* A radar needs at least a triangle to read as a shape. */}
            {scores.length >= 3 && <SkillsRadar skills={scores} />}
            <ul className="grid gap-2.5">
              {scores.map((s) => (
                <li key={s.skill} className="grid gap-1">
                  <div className="flex items-baseline justify-between gap-4 text-sm">
                    <span className="capitalize">{s.skill}</span>
                    <span className="font-mono text-muted-foreground">{s.score}</span>
                  </div>
                  <div
                    className="h-1.5 overflow-hidden rounded-full bg-muted"
                    role="presentation"
                  >
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${(s.score / max) * 100}%`, backgroundColor: BAR }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
