"use client";

import { useFormatter, useTranslations } from "next-intl";
import dynamic from "next/dynamic";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { SortableTableHead, TablePagination } from "@/components/ui/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { parseServerDate } from "@/lib/datetime";
import { useChallenges } from "@/lib/hooks/use-challenges";
import { useDataTable } from "@/lib/hooks/use-data-table";
import {
  useJudgingList,
  useJudgingQueue,
  useJudgingSource,
  useOverrideVerdict,
  useRejudge,
  useRejudgeProblem,
  useSubmissionHistory,
} from "@/lib/hooks/use-judge";
import type {
  Judging,
  JudgingListFilters,
  JudgingVerdict,
  RejudgeScope,
  StaffJudgingRow,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { toast } from "@/stores/toast";

// The submitted code, read-only — CodeMirror, loaded only when a judging is
// opened (as on the problem page).
const CodeEditor = dynamic(
  () => import("@/components/challenges/code-editor").then((m) => m.CodeEditor),
  { ssr: false, loading: () => <Skeleton className="h-64 w-full" /> },
);

const VERDICTS: JudgingVerdict[] = [
  "accepted",
  "wrong_answer",
  "time_limit",
  "memory_limit",
  "output_limit",
  "runtime_error",
  "compile_error",
  "internal_error",
];
const OVERRIDE_VERDICTS = VERDICTS.filter((v) => v !== "internal_error");

const formatMs = (ms: number | null) => (ms == null ? "—" : `${ms} ms`);
const formatKb = (kb: number | null) =>
  kb == null ? "—" : kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb} KB`;

function verdictVariant(verdict: string | null): "success" | "destructive" | "muted" {
  if (verdict === "accepted") return "success";
  if (!verdict || verdict === "internal_error") return "muted";
  return "destructive";
}

/** The result chip: waiting / judging, or the verdict — plus where it came from. */
function ResultChip({ row }: { row: Pick<StaffJudgingRow, "status" | "verdict" | "origin"> }) {
  const t = useTranslations("judging");
  const tv = useTranslations("challenges.code.verdict");
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {row.status === "queued" || row.status === "running" ? (
        <Badge variant="outline">{row.status === "queued" ? t("statusQueued") : t("statusRunning")}</Badge>
      ) : (
        <Badge variant={verdictVariant(row.verdict)}>{tv(row.verdict ?? "internal_error")}</Badge>
      )}
      {row.origin !== "submission" && (
        <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
          {row.origin === "rejudge" ? t("originRejudge") : t("originOverride")}
        </span>
      )}
    </span>
  );
}

export function JudgingConsole({
  competitionId,
  canAct,
}: {
  competitionId: string;
  canAct: boolean;
}) {
  const t = useTranslations("judging");
  const tv = useTranslations("challenges.code.verdict");
  const format = useFormatter();
  const challenges = useChallenges(competitionId);
  const queue = useJudgingQueue(competitionId);

  const [problem, setProblem] = useState("");
  const [result, setResult] = useState("");
  const [showRuns, setShowRuns] = useState(false);
  const [open, setOpen] = useState<StaffJudgingRow | null>(null);
  const [bulkOpen, setBulkOpen] = useState(false);

  const filters: JudgingListFilters = {
    challenge_id: problem || undefined,
    verdict: result && result !== "pending" ? result : undefined,
    kind: showRuns ? undefined : "submit",
  };
  const list = useJudgingList(competitionId, filters);
  const problems = useMemo(
    () => (challenges.data ?? []).filter((c) => c.flag_type === "programming"),
    [challenges.data],
  );
  const items = useMemo(() => {
    const all = list.data?.items ?? [];
    return result === "pending" ? all.filter((r) => r.status === "queued" || r.status === "running") : all;
  }, [list.data, result]);

  const who = (r: StaffJudgingRow) => r.team_name ?? r.user_name;
  const table = useDataTable(items, {
    columns: {
      submitted: { value: (r: StaffJudgingRow) => r.created_at, defaultDir: "desc" },
      who,
      problem: (r: StaffJudgingRow) => r.challenge_title,
      result: (r: StaffJudgingRow) => r.verdict ?? r.status,
    },
  });
  const dir = (key: string) => (table.sort?.key === key ? table.sort.dir : null);
  const when = (iso: string) =>
    format.dateTime(parseServerDate(iso), { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });

  const q = queue.data;
  return (
    <div className="space-y-5">
      {q && (
        <Card>
          <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 py-4 text-sm">
            <span className="flex items-center gap-2">
              <span
                className={cn("h-2 w-2 rounded-full", q.queued + q.running > 0 ? "animate-pulse bg-primary" : "bg-success")}
                aria-hidden="true"
              />
              {t("queueLine", { queued: q.queued, running: q.running })}
            </span>
            {q.site_queued > q.queued && (
              <span className="text-muted-foreground">{t("queueSite", { count: q.site_queued })}</span>
            )}
            {!q.judge_enabled && (
              <span role="alert" className="text-destructive">
                {t("judgeOff")}
              </span>
            )}
          </CardContent>
        </Card>
      )}

      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="judging-problem" className="text-xs text-muted-foreground">
            {t("filterProblem")}
          </Label>
          <Select id="judging-problem" value={problem} onChange={(e) => setProblem(e.target.value)} className="h-9 w-auto min-w-[12rem]">
            <option value="">{t("allProblems")}</option>
            {problems.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="judging-result" className="text-xs text-muted-foreground">
            {t("filterResult")}
          </Label>
          <Select id="judging-result" value={result} onChange={(e) => setResult(e.target.value)} className="h-9 w-auto min-w-[10rem]">
            <option value="">{t("allResults")}</option>
            <option value="pending">{t("pending")}</option>
            {VERDICTS.map((v) => (
              <option key={v} value={v}>
                {tv(v)}
              </option>
            ))}
          </Select>
        </div>
        <label className="flex h-9 items-center gap-2 text-sm">
          <input type="checkbox" checked={showRuns} onChange={(e) => setShowRuns(e.target.checked)} />
          {t("includeRuns")}
        </label>
        {canAct && problem && (
          <Button type="button" variant="outline" className="ml-auto" onClick={() => setBulkOpen(true)}>
            {t("rejudgeProblem")}
          </Button>
        )}
      </div>

      {list.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : items.length === 0 ? (
        <EmptyState title={t("emptyTitle")} description={t("emptyDescription")} />
      ) : (
        <Card>
          <CardContent className="pt-5">
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableTableHead active={dir("submitted")} onSort={() => table.toggleSort("submitted")}>
                    {t("colTime")}
                  </SortableTableHead>
                  <SortableTableHead active={dir("who")} onSort={() => table.toggleSort("who")}>
                    {t("colWho")}
                  </SortableTableHead>
                  <SortableTableHead active={dir("problem")} onSort={() => table.toggleSort("problem")}>
                    {t("colProblem")}
                  </SortableTableHead>
                  <TableHead>{t("colLanguage")}</TableHead>
                  <SortableTableHead active={dir("result")} onSort={() => table.toggleSort("result")}>
                    {t("colResult")}
                  </SortableTableHead>
                  <TableHead>{t("colTests")}</TableHead>
                  <TableHead className="text-right">{t("colUsage")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {table.rows.map((r) => (
                  <TableRow
                    key={r.id}
                    className="cursor-pointer"
                    onClick={() => setOpen(r)}
                    onKeyDown={(e) => e.key === "Enter" && setOpen(r)}
                    tabIndex={0}
                  >
                    <TableCell className="whitespace-nowrap text-muted-foreground">{when(r.created_at)}</TableCell>
                    <TableCell className="font-medium">
                      {who(r)}
                      {r.kind === "run" && <span className="ml-2 text-xs text-muted-foreground">{t("runTag")}</span>}
                    </TableCell>
                    <TableCell>{r.challenge_title}</TableCell>
                    <TableCell className="text-muted-foreground">{r.language_name}</TableCell>
                    <TableCell>
                      <ResultChip row={r} />
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {r.tests_total != null ? `${r.tests_passed ?? 0}/${r.tests_total}` : "—"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right font-mono text-xs text-muted-foreground">
                      {formatMs(r.max_time_ms)} · {formatKb(r.max_memory_kb)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <TablePagination table={table} noun={t("noun")} className="mt-4" />
            {list.data && list.data.total > list.data.items.length && (
              <p className="mt-2 text-xs text-muted-foreground">
                {t("showingLatest", { shown: list.data.items.length, total: list.data.total })}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {open && (
        <JudgingDetail
          competitionId={competitionId}
          row={open}
          canAct={canAct}
          onClose={() => setOpen(null)}
        />
      )}
      {bulkOpen && problem && (
        <RejudgeProblemDialog
          competitionId={competitionId}
          challengeId={problem}
          title={problems.find((c) => c.id === problem)?.title ?? ""}
          onClose={() => setBulkOpen(false)}
        />
      )}
    </div>
  );
}

function RejudgeProblemDialog({
  competitionId,
  challengeId,
  title,
  onClose,
}: {
  competitionId: string;
  challengeId: string;
  title: string;
  onClose: () => void;
}) {
  const t = useTranslations("judging");
  const rejudge = useRejudgeProblem(competitionId);
  const [only, setOnly] = useState<RejudgeScope>("all");
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("rejudgeProblemTitle", { title })}</DialogTitle>
          <DialogDescription>{t("rejudgeProblemDescription")}</DialogDescription>
        </DialogHeader>
        <fieldset className="space-y-2">
          {(["all", "accepted", "not_accepted"] as const).map((scope) => (
            <label key={scope} className="flex items-start gap-2 text-sm">
              <input
                type="radio"
                name="rejudge-scope"
                className="mt-1"
                checked={only === scope}
                onChange={() => setOnly(scope)}
              />
              <span>{t(`scope.${scope}`)}</span>
            </label>
          ))}
        </fieldset>
        {rejudge.isError && (
          <p role="alert" className="text-sm text-destructive">
            {(rejudge.error as Error).message}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            type="button"
            disabled={rejudge.isPending}
            onClick={() =>
              rejudge.mutate(
                { challengeId, only },
                {
                  onSuccess: (res) => {
                    const notes = [
                      res.skipped ? t("rejudgeSkipped", { count: res.skipped }) : null,
                      res.overridden ? t("rejudgeKeptOverrides", { count: res.overridden }) : null,
                    ].filter(Boolean);
                    toast(t("rejudgeQueued", { count: res.queued }), {
                      variant: "success",
                      description: notes.length ? notes.join(" ") : undefined,
                    });
                    onClose();
                  },
                },
              )
            }
          >
            {t("rejudgeConfirm")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function JudgingDetail({
  competitionId,
  row,
  canAct,
  onClose,
}: {
  competitionId: string;
  row: StaffJudgingRow;
  canAct: boolean;
  onClose: () => void;
}) {
  const t = useTranslations("judging");
  const tv = useTranslations("challenges.code.verdict");
  const format = useFormatter();
  const history = useSubmissionHistory(competitionId, row.code_submission_id);
  const source = useJudgingSource(competitionId, row.kind === "submit" ? row.id : null);
  const rejudge = useRejudge(competitionId);
  const override = useOverrideVerdict(competitionId);
  const [overriding, setOverriding] = useState(false);
  const [verdict, setVerdict] = useState<string>("accepted");
  const [reason, setReason] = useState("");

  const judgings = history.data ?? [];
  // The verdict that counts: the newest finished judging.
  const current: Judging | undefined =
    [...judgings].reverse().find((j) => j.status === "done") ?? judgings[judgings.length - 1];
  const active = judgings.some((j) => j.status === "queued" || j.status === "running");
  const when = (iso: string) =>
    format.dateTime(parseServerDate(iso), { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {row.team_name ?? row.user_name} · {row.challenge_title}
          </DialogTitle>
          <DialogDescription>
            {t("detailMeta", { language: row.language_name, time: when(row.submitted_at) })}
          </DialogDescription>
        </DialogHeader>

        {history.isLoading || !current ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <div className="space-y-5">
            <section className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <ResultChip row={current} />
                <span className="font-mono text-xs text-muted-foreground">
                  {current.tests_total != null && `${current.tests_passed ?? 0}/${current.tests_total} · `}
                  {formatMs(current.max_time_ms)} · {formatKb(current.max_memory_kb)}
                </span>
              </div>
              {current.origin === "override" && current.note && (
                <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
                  {t("overrideNote", { name: current.requested_by_name ?? "—", note: current.note })}
                </p>
              )}
              {current.error && (
                <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm">
                  {current.error}
                </p>
              )}
              {current.tests.length > 0 && (
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="py-1 font-medium">{t("test")}</th>
                      <th className="py-1 font-medium">{t("colResult")}</th>
                      <th className="py-1 text-right font-medium">{t("colUsage")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {current.tests.map((r) => (
                      <tr key={r.index}>
                        <td className="py-1.5">
                          {r.sample ? t("exampleN", { n: r.index + 1 }) : t("hiddenN", { n: r.index + 1 })}
                        </td>
                        <td className="py-1.5">
                          <Badge variant={verdictVariant(r.verdict)}>{tv(r.verdict)}</Badge>
                        </td>
                        <td className="py-1.5 text-right font-mono text-xs text-muted-foreground">
                          {formatMs(r.time_ms)} · {formatKb(r.memory_kb)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {current.compile_output && (
                <details open={current.verdict === "compile_error"}>
                  <summary className="cursor-pointer text-sm font-medium">{t("compilerOutput")}</summary>
                  <pre className="mt-2 max-h-48 overflow-auto rounded-md border border-border bg-muted/40 px-3 py-2 font-mono text-xs">
                    {current.compile_output}
                  </pre>
                </details>
              )}
            </section>

            {canAct && row.kind === "submit" && (
              <section className="space-y-3 rounded-md border border-border p-3">
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    disabled={active || rejudge.isPending}
                    title={active ? t("alreadyQueued") : undefined}
                    onClick={() =>
                      rejudge.mutate(row.id, {
                        onSuccess: () => toast(t("rejudgeQueued", { count: 1 }), { variant: "success" }),
                        onError: (e) => toast(t("actionFailed"), { description: (e as Error).message, variant: "destructive" }),
                      })
                    }
                  >
                    {t("rejudge")}
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => setOverriding((v) => !v)}>
                    {t("override")}
                  </Button>
                </div>
                {overriding && (
                  <form
                    className="grid gap-3"
                    onSubmit={(e) => {
                      e.preventDefault();
                      override.mutate(
                        { judgingId: row.id, verdict, reason },
                        {
                          onSuccess: () => {
                            toast(t("overridden"), { variant: "success" });
                            setOverriding(false);
                            setReason("");
                          },
                        },
                      );
                    }}
                  >
                    <p className="text-xs text-muted-foreground">{t("overrideHint")}</p>
                    <div className="flex flex-wrap items-center gap-2">
                      <Label htmlFor="override-verdict" className="text-sm">
                        {t("overrideVerdict")}
                      </Label>
                      <Select
                        id="override-verdict"
                        value={verdict}
                        onChange={(e) => setVerdict(e.target.value)}
                        className="h-9 w-auto"
                      >
                        {OVERRIDE_VERDICTS.map((v) => (
                          <option key={v} value={v}>
                            {tv(v)}
                          </option>
                        ))}
                      </Select>
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="override-reason" className="text-sm">
                        {t("overrideReason")}
                      </Label>
                      <textarea
                        id="override-reason"
                        required
                        minLength={3}
                        maxLength={1000}
                        rows={2}
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                      />
                    </div>
                    {override.isError && (
                      <p role="alert" className="text-sm text-destructive">
                        {(override.error as Error).message}
                      </p>
                    )}
                    <div>
                      <Button type="submit" disabled={override.isPending || reason.trim().length < 3}>
                        {t("overrideSave")}
                      </Button>
                    </div>
                  </form>
                )}
              </section>
            )}

            {row.kind === "submit" && (
              <section className="space-y-2">
                <h3 className="text-sm font-semibold">{t("code")}</h3>
                <div className="h-72 overflow-hidden rounded-md border border-border">
                  {source.data ? (
                    <CodeEditor
                      value={source.data.source}
                      languageKey={source.data.language_key}
                      ariaLabel={t("code")}
                      readOnly
                    />
                  ) : source.isError ? (
                    <p className="p-3 text-sm text-destructive">{(source.error as Error).message}</p>
                  ) : (
                    <Skeleton className="h-full w-full" />
                  )}
                </div>
              </section>
            )}

            {judgings.length > 1 && (
              <section className="space-y-2">
                <h3 className="text-sm font-semibold">{t("history")}</h3>
                <ol className="divide-y divide-border rounded-md border border-border text-sm">
                  {judgings.map((j) => (
                    <li key={j.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
                      <span className="text-xs text-muted-foreground">{when(j.created_at)}</span>
                      <ResultChip row={j} />
                      {j.requested_by_name && (
                        <span className="text-xs text-muted-foreground">{t("byName", { name: j.requested_by_name })}</span>
                      )}
                      {j.note && <span className="w-full text-xs text-muted-foreground">“{j.note}”</span>}
                    </li>
                  ))}
                </ol>
              </section>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
