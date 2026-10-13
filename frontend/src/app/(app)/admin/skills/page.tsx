"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { SectionHeader } from "@/components/app/section-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
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
import { SkillsRadar } from "@/components/skills/skills-radar";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Select } from "@/components/ui/select";
import { useAccess } from "@/lib/hooks/use-permissions";
import {
  useAdminUserSkills,
  useExportSkillMatrix,
  useSkillMatrix,
} from "@/lib/hooks/use-skills";
import type { SkillCell, SkillMatrix, SkillWindow } from "@/lib/types";
import { toast } from "@/stores/toast";

// Admin → Skills. The cross-competition users×skills matrix (#364/#435,
// ADR-0039) — enriched cells: weighted points (decay rarity priced in at solve
// time), coverage against genuine opportunity, and a percentile heat map as the
// scale-free comparator (points don't normalize across competitions). Gated on
// view_global_analytics and paginated + sorted server-side so ordering is
// truthful across pages.
const PAGE_SIZE = 25;

/** Heat background steps from the percentile — the instance's accent
 * (`--primary`, the colour the admin chose for this theme) at rising alpha, so
 * the heat map tracks the selected palette rather than a fixed chart hue.
 * Readable in both light and dark (tokens only, §9). */
function heatColor(pct: number): string | undefined {
  const alpha = pct >= 90 ? 0.55 : pct >= 75 ? 0.4 : pct >= 50 ? 0.26 : pct >= 25 ? 0.14 : 0;
  return alpha ? `hsl(var(--primary) / ${alpha})` : undefined;
}

export default function AdminSkillsPage() {
  const t = useTranslations("admin.skills");
  const access = useAccess();
  const canView = access.has("view_global_analytics");
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState<string>("total");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  // Activity window (#440): bounds solves/attempts/hints, never opportunity.
  const [window, setWindow] = useState<SkillWindow>("all");
  // Display-name search. `search` is the input; `q` is debounced so typing
  // doesn't fire a request per keystroke (the users-directory pattern). Search
  // is server-side (`?q=`) over every tracked participant, so it finds someone
  // on a later page — committing a search resets to the first page.
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const handle = setTimeout(() => {
      setQ(search);
      setOffset(0);
    }, 250);
    return () => clearTimeout(handle);
  }, [search]);
  // Drill-down target — a row click opens the per-user dialog.
  const [selectedUser, setSelectedUser] = useState<string | null>(null);
  const matrix = useSkillMatrix(
    { limit: PAGE_SIZE, offset, sort, direction, window, q },
    canView,
  );

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
      ) : matrix.data.users.length === 0 && !q ? (
        // Truly no data — distinct from a search that matched nobody (handled
        // inside the card so the search box stays usable).
        <EmptyState title={t("emptyTitle")} description={t("emptyDescription")} />
      ) : (
        <MatrixCard
          data={matrix.data}
          offset={offset}
          onOffset={setOffset}
          sort={sort}
          direction={direction}
          onSort={onSort}
          window={window}
          onWindow={(w) => {
            setWindow(w);
            setOffset(0);
          }}
          search={search}
          onSearch={setSearch}
          onSelectUser={setSelectedUser}
        />
      )}
      <DrilldownDialog
        userId={selectedUser}
        window={window}
        onOpenChange={() => setSelectedUser(null)}
      />
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
        {cell.first_bloods > 0 && ` · ${t("fbSuffix", { count: cell.first_bloods })}`}
      </span>
    </div>
  );
}

/** The per-user drill-down (#440): the matrix row opened up — radar, efficiency
 * stats, and the underlying solves with context. Fetched on open. */
function DrilldownDialog({
  userId,
  window,
  onOpenChange,
}: {
  userId: string | null;
  window: SkillWindow;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("admin.skills");
  const detail = useAdminUserSkills(userId, window, Boolean(userId));
  const d = detail.data;
  const radar = (d?.skills ?? []).map((s) => ({ skill: s.skill, score: s.weighted }));
  return (
    <Dialog open={Boolean(userId)} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{d ? d.display_name : t("drilldownLoading")}</DialogTitle>
          <DialogDescription>{t(`window.${window}`)}</DialogDescription>
        </DialogHeader>
        {detail.isLoading || !d ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <div className="grid gap-6">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <DrillStat value={d.total_weighted} label={t("colTotal")} />
              <DrillStat value={d.total} label={t("drillSolves")} />
              <DrillStat
                value={d.skills.reduce((n, row) => n + row.first_bloods, 0)}
                label={t("drillFirstBloods")}
              />
              <DrillStat
                value={
                  d.total > 0
                    ? (
                        d.skills.reduce((n, row) => n + row.attempts, 0) / d.total
                      ).toFixed(1)
                    : "–"
                }
                label={t("drillAttemptsPerSolve")}
              />
            </div>
            {radar.length >= 3 && <SkillsRadar skills={radar} />}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("drillColChallenge")}</TableHead>
                  <TableHead>{t("drillColCompetition")}</TableHead>
                  <TableHead>{t("drillColSkill")}</TableHead>
                  <TableHead className="text-right">{t("drillColPoints")}</TableHead>
                  <TableHead className="text-right">{t("drillColAttempts")}</TableHead>
                  <TableHead className="text-right">{t("drillColHints")}</TableHead>
                  <TableHead className="text-right">{t("drillColWhen")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.solves.map((solve, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-medium">
                      {solve.challenge_title}
                      {solve.first_blood && (
                        <span
                          className="ml-1.5 text-[0.65rem] font-semibold text-primary"
                          title={t("fbSuffix", { count: 1 })}
                        >
                          {t("fbMark")}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {solve.competition_name}
                    </TableCell>
                    <TableCell className="capitalize text-muted-foreground">
                      {solve.skill}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {solve.points_awarded}
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">
                      {solve.attempts}
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">
                      {solve.hints}
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground">
                      {new Date(solve.solved_at).toLocaleDateString()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function DrillStat({ value, label }: { value: string | number; label: string }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="text-base font-semibold tabular-nums">{value}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  );
}

const WINDOW_OPTIONS: SkillWindow[] = ["all", "365", "90", "30"];

function MatrixCard({
  data,
  offset,
  onOffset,
  sort,
  direction,
  onSort,
  window,
  onWindow,
  search,
  onSearch,
  onSelectUser,
}: {
  data: SkillMatrix;
  offset: number;
  onOffset: (next: number) => void;
  sort: string;
  direction: "asc" | "desc";
  onSort: (column: string) => void;
  window: SkillWindow;
  onWindow: (w: SkillWindow) => void;
  search: string;
  onSearch: (value: string) => void;
  onSelectUser: (userId: string) => void;
}) {
  const t = useTranslations("admin.skills");
  const exportCsv = useExportSkillMatrix();
  const from = offset + 1;
  const to = Math.min(offset + PAGE_SIZE, data.total_users);
  const arrow = direction === "desc" ? "↓" : "↑";

  function onExport() {
    exportCsv.mutate(window, {
      onError: () => toast(t("exportError"), { variant: "destructive" }),
    });
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0">
        <CardTitle>{t("cardTitle", { count: data.total_users })}</CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            type="search"
            aria-label={t("searchLabel")}
            placeholder={t("searchPlaceholder")}
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            className="w-48"
          />
          <Select
            aria-label={t("windowLabel")}
            value={window}
            onChange={(e) => onWindow(e.target.value as SkillWindow)}
            className="w-40"
          >
            {WINDOW_OPTIONS.map((w) => (
              <option key={w} value={w}>
                {t(`window.${w}`)}
              </option>
            ))}
          </Select>
        <Button
          variant="outline"
          size="sm"
          disabled={exportCsv.isPending}
          onClick={onExport}
        >
          {exportCsv.isPending ? t("exporting") : t("export")}
        </Button>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4">
        {data.users.length === 0 ? (
          // A search that matched nobody — the box above stays usable to retype.
          <p className="py-8 text-center text-sm text-muted-foreground">
            {t("noMatches", { search })}
          </p>
        ) : (
          <>
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
                <TableRow
                  key={u.user_id}
                  className="cursor-pointer"
                  onClick={() => onSelectUser(u.user_id)}
                >
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
                        title={
                          cell
                            ? t("cellDetail", {
                                pct: cell.pct,
                                attempts: cell.attempts,
                                hints: cell.hints,
                                fb: cell.first_bloods,
                              })
                            : undefined
                        }
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
          </>
        )}
      </CardContent>
    </Card>
  );
}
