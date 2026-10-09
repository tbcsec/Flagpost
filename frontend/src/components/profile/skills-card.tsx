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

export function MySkillsCard() {
  const t = useTranslations("profile.skills");
  const { data, isLoading, isError } = useMySkills();

  const scores = data?.skills ?? [];
  const max = radarMax(scores.map((s) => s.score));

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
            <p className="text-sm text-muted-foreground">
              {t("summary", {
                total: data?.total ?? 0,
                competitions: data?.competitions_played ?? 0,
              })}
            </p>
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
