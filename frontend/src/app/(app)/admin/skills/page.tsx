"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { SectionHeader } from "@/components/app/section-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAccess } from "@/lib/hooks/use-permissions";
import { useExportSkillMatrix, useSkillMatrix } from "@/lib/hooks/use-skills";
import type { SkillCell, SkillMatrix } from "@/lib/types";
import { toast } from "@/stores/toast";

// Admin → Skills. The cross-competition users×skills matrix (#364/#435,
// ADR-0039) — enriched cells: weighted points (decay rarity priced in at solve
// time), coverage against genuine opportunity, and a percentile heat map as the
// scale-free comparator (points don't normalize across competitions). Gated on
// view_global_analytics and paginated + sorted server-side so ordering is
// truthful across pages.
const PAGE_SIZE = 25;

/** Heat background steps from the percentile — the radar's accent at rising
 * alpha, readable in both themes (tokens only, §9). */
function heatColor(pct: number): string | undefined {
  const alpha = pct >= 90 ? 0.55 : pct >= 75 ? 0.4 : pct >= 50 ? 0.26 : pct >= 25 ? 0.14 : 0;
  return alpha ? `hsl(var(--chart-1) / ${alpha})` : undefined;
}

export default function AdminSkillsPage() {
  const t = useTranslations("admin.skills");
  const access = useAccess();
  const canView = access.has("view_global_analytics");
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState<string>("total");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const matrix = useSkillMatrix({ limit: PAGE_SIZE, offset, sort, direction }, canView);

  function onSort(column: string) {
    if (sort === column) {
      setDirection((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSort(column);
      setDirection("desc");
    }
    setOffset(0);
  }

  return (
    <>
      <SectionHeader title={t("title")} subtitle={t("subtitle")} />

      {!access.ready ? (
        <Skeleton className="h-24 w-full" />
      ) : !canView ? (
        <EmptyState title={t("noAccessTitle")} description={t("noAccessDescription")} />
      ) : matrix.isLoading || !matrix.data ? (
        <Skeleton className="h-64 w-full" />
      ) : matrix.data.users.length === 0 ? (
        <EmptyState title={t("emptyTitle")} description={t("emptyDescription")} />
      ) : (
        <MatrixCard
          data={matrix.data}
          offset={offset}
          onOffset={setOffset}
          sort={sort}
          direction={direction}
          onSort={onSort}
        />
      )}
    </>
  );
}

function CellValue({ cell }: { cell: SkillCell | undefined }) {
  const t = useTranslations("admin.skills");
  if (!cell) {
    // Untouched category — not a zero score, an absence.
    return <span className="text-muted-foreground/50">–</span>;
  }
  return (
    <div className="grid gap-0.5 leading-tight">
      <span className="font-mono tabular-nums">{cell.weighted}</span>
      <span className="text-[0.7rem] text-muted-foreground tabular-nums">
        {t("coverage", { solved: cell.solved, available: cell.available })}
      </span>
    </div>
  );
}

function MatrixCard({
  data,
  offset,
  onOffset,
  sort,
  direction,
  onSort,
}: {
  data: SkillMatrix;
  offset: number;
  onOffset: (next: number) => void;
  sort: string;
  direction: "asc" | "desc";
  onSort: (column: string) => void;
}) {
  const t = useTranslations("admin.skills");
  const exportCsv = useExportSkillMatrix();
  const from = offset + 1;
  const to = Math.min(offset + PAGE_SIZE, data.total_users);
  const arrow = direction === "desc" ? "↓" : "↑";

  function onExport() {
    exportCsv.mutate(undefined, {
      onError: () => toast(t("exportError"), { variant: "destructive" }),
    });
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0">
        <CardTitle>{t("cardTitle", { count: data.total_users })}</CardTitle>
        <Button
          variant="outline"
          size="sm"
          disabled={exportCsv.isPending}
          onClick={onExport}
        >
          {exportCsv.isPending ? t("exporting") : t("export")}
        </Button>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("colUser")}</TableHead>
                {data.skills.map((skill) => (
                  <TableHead key={skill} className="text-right">
                    <button
                      type="button"
                      className="capitalize hover:text-foreground"
                      onClick={() => onSort(skill)}
                    >
                      {skill}
                      {sort === skill ? ` ${arrow}` : ""}
                    </button>
                  </TableHead>
                ))}
                <TableHead className="text-right">
                  <button
                    type="button"
                    className="hover:text-foreground"
                    onClick={() => onSort("total")}
                  >
                    {t("colTotal")}
                    {sort === "total" ? ` ${arrow}` : ""}
                  </button>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.users.map((u) => (
                <TableRow key={u.user_id}>
                  <TableCell className="font-medium">{u.display_name}</TableCell>
                  {data.skills.map((skill) => {
                    const cell = u.scores[skill];
                    return (
                      <TableCell
                        key={skill}
                        className="text-right"
                        style={
                          cell ? { backgroundColor: heatColor(cell.pct) } : undefined
                        }
                        title={cell ? t("cellTitle", { pct: cell.pct }) : undefined}
                      >
                        <CellValue cell={cell} />
                      </TableCell>
                    );
                  })}
                  <TableCell className="text-right">
                    <div className="grid gap-0.5 leading-tight">
                      <span className="font-mono tabular-nums">{u.total_weighted}</span>
                      <span className="text-[0.7rem] text-muted-foreground tabular-nums">
                        {t("totalSolves", { count: u.total })}
                      </span>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {/* Population footer — "where is the community weak" at a glance. */}
              <TableRow className="bg-muted/40">
                <TableCell className="text-xs font-medium text-muted-foreground">
                  {t("footerLabel")}
                </TableCell>
                {data.skills.map((skill) => {
                  const pop = data.population[skill];
                  return (
                    <TableCell
                      key={skill}
                      className="text-right text-[0.7rem] text-muted-foreground tabular-nums"
                    >
                      {pop
                        ? t("footerCell", {
                            solvers: pop.solvers,
                            mean: pop.mean_weighted,
                          })
                        : "–"}
                    </TableCell>
                  );
                })}
                <TableCell />
              </TableRow>
            </TableBody>
          </Table>
        </div>

        <p className="text-xs text-muted-foreground">{t("legend")}</p>

        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">
            {t("range", { from, to, total: data.total_users })}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={offset === 0}
              onClick={() => onOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              {t("prev")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={offset + PAGE_SIZE >= data.total_users}
              onClick={() => onOffset(offset + PAGE_SIZE)}
            >
              {t("next")}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
