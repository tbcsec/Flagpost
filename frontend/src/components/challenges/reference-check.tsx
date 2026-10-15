"use client";

// The reference-solution check (#450): an author runs a solution they know is
// right against every test — examples and hidden — through the real judge, to
// catch a wrong expected output or a too-tight limit before competitors do.
// Optional and never a gate on publishing; it sits under the test cases as a
// gentle nudge. Every test is reported (the check doesn't stop at the first
// failure), numbered as in the list above it.

import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useJudgeStatus,
  useReferenceCheck,
  useRunReferenceCheck,
} from "@/lib/hooks/use-judge";
import { useRelativeTime } from "@/lib/hooks/use-relative-time";
import type { JudgeProblem, Judging, JudgingRun } from "@/lib/types";
import { cn } from "@/lib/utils";

const CodeEditor = dynamic(
  () => import("@/components/challenges/code-editor").then((m) => m.CodeEditor),
  { ssr: false, loading: () => <Skeleton className="h-60 w-full" /> },
);

// The server's source cap (routers/judge_submissions.MAX_SOURCE_BYTES).
const MAX_SOURCE_BYTES = 128 * 1024;

const formatMs = (ms: number | null) => (ms == null ? "—" : `${ms} ms`);
const formatKb = (kb: number | null) =>
  kb == null ? "—" : kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb} KB`;

function verdictVariant(verdict: string | null): "success" | "destructive" | "muted" {
  if (verdict === "accepted") return "success";
  if (!verdict || verdict === "internal_error") return "muted";
  return "destructive";
}

export function ReferenceCheckPanel({
  competitionId,
  challengeId,
  problem,
}: {
  competitionId: string;
  challengeId: string;
  problem: JudgeProblem;
}) {
  const t = useTranslations("challenges.admin.programming.reference");
  const status = useJudgeStatus(competitionId);
  const check = useReferenceCheck(competitionId, challengeId);
  const run = useRunReferenceCheck(competitionId, challengeId);
  const ago = useRelativeTime();
  const [editing, setEditing] = useState(false);

  const ready = status.data?.ready ?? false;
  const languages = (status.data?.languages ?? []).filter(
    (l) => !problem.allowed_languages || problem.allowed_languages.includes(l.key),
  );
  const data = check.data;
  const judging = data?.judging ?? null;
  const active = judging?.status === "queued" || judging?.status === "running";
  // The last check's language may since have been disallowed for the problem
  // (or disabled): then it can't simply be run again.
  const storedLanguage = languages.some((l) => l.key === data?.language_key)
    ? data?.language_key ?? null
    : null;

  return (
    <section aria-labelledby="reference-check-title" className="space-y-3 rounded-md bg-muted/40 p-3">
      <div className="space-y-1">
        <h4 id="reference-check-title" className="text-sm font-medium">
          {t("title")}
        </h4>
        <p className="text-xs text-muted-foreground">{t("description")}</p>
      </div>

      {judging && data && (
        <CheckResult
          judging={judging}
          stale={data.stale}
          meta={t("meta", {
            language: judging.language_name,
            name: data.run_by_name ?? "—",
            time: ago(judging.created_at),
          })}
        />
      )}

      <div className="flex flex-wrap items-center gap-2">
        {judging && data?.source ? (
          <>
            <Button
              type="button"
              size="sm"
              disabled={!ready || active || run.isPending || !storedLanguage}
              onClick={() =>
                storedLanguage && run.mutate({ language: storedLanguage, source: data.source! })
              }
            >
              {t("runAgain")}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!ready || active}
              onClick={() => setEditing(true)}
            >
              {t("change")}
            </Button>
          </>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!ready || active}
            onClick={() => setEditing(true)}
          >
            {t("start")}
          </Button>
        )}
        {!ready && status.data && (
          <span className="text-xs text-muted-foreground">{t("notReady")}</span>
        )}
      </div>
      {run.isError && !editing && (
        <p role="alert" className="text-sm text-destructive">
          {(run.error as Error).message}
        </p>
      )}

      {editing && (
        <ReferenceDialog
          languages={languages}
          initialLanguage={storedLanguage ?? languages[0]?.key ?? ""}
          initialSource={data?.source ?? ""}
          pending={run.isPending}
          error={run.isError ? (run.error as Error).message : null}
          onClose={() => {
            run.reset();
            setEditing(false);
          }}
          onRun={(language, source) =>
            run.mutate({ language, source }, { onSuccess: () => setEditing(false) })
          }
        />
      )}
    </section>
  );
}

function CheckResult({ judging, stale, meta }: { judging: Judging; stale: boolean; meta: string }) {
  const t = useTranslations("challenges.admin.programming.reference");
  const tp = useTranslations("challenges.admin.programming");
  const tv = useTranslations("challenges.code.verdict");

  let summary: { text: string; tone: "success" | "destructive" | "muted" | "outline" };
  if (judging.status === "queued") {
    summary = {
      text: judging.queue_position
        ? t("queuedAt", { position: judging.queue_position })
        : t("queued"),
      tone: "outline",
    };
  } else if (judging.status === "running") {
    summary = { text: t("judging"), tone: "outline" };
  } else if (judging.status === "failed" || judging.verdict === "internal_error") {
    summary = { text: t("couldNotRun"), tone: "muted" };
  } else if (judging.verdict === "compile_error") {
    summary = { text: tv("compile_error"), tone: "destructive" };
  } else if (judging.verdict === "accepted") {
    summary = { text: t("passed", { total: judging.tests_total ?? 0 }), tone: "success" };
  } else {
    const total = judging.tests_total ?? judging.tests.length;
    const failed = total - (judging.tests_passed ?? 0);
    summary = { text: t("failedCount", { failed, total }), tone: "destructive" };
  }

  const done = judging.status === "done";
  // A harness that predates #450 stops at the first failure; whatever didn't
  // run shows as such rather than silently missing.
  const missing: JudgingRun[] =
    done && judging.verdict !== "compile_error"
      ? Array.from(
          { length: Math.max(0, (judging.tests_total ?? 0) - judging.tests.length) },
          (_, i) => ({
            index: judging.tests.length + i,
            sample: false,
            verdict: "internal_error",
            time_ms: null,
            memory_kb: null,
            output: null,
          }),
        )
      : [];

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={summary.tone}>{summary.text}</Badge>
        <span className="text-xs text-muted-foreground">{meta}</span>
      </div>
      {done && stale && (
        <p role="status" className="rounded-md border border-warning/40 bg-warning/15 px-3 py-2 text-sm text-foreground">
          {t("stale")}
        </p>
      )}
      {judging.error && (
        <p className="rounded-md border border-border bg-background px-3 py-2 text-sm text-muted-foreground">
          {judging.error}
        </p>
      )}
      {judging.compile_output && judging.verdict === "compile_error" && (
        <pre className="max-h-48 overflow-auto rounded-md border border-border bg-background px-3 py-2 font-mono text-xs">
          {judging.compile_output}
        </pre>
      )}
      {(judging.tests.length > 0 || missing.length > 0) && (
        <ol className="max-h-72 divide-y divide-border overflow-auto rounded-md border border-border bg-background">
          {[...judging.tests, ...missing].map((r, i) => {
            const notRun = i >= judging.tests.length;
            return (
              <li key={r.index} className="flex items-center gap-3 px-3 py-1.5 text-sm">
                <span className="w-6 shrink-0 text-xs text-muted-foreground">{r.index + 1}</span>
                {!notRun && (
                  <span
                    className={cn(
                      "rounded-full px-2 py-px text-[11px] font-medium",
                      r.sample ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
                    )}
                  >
                    {r.sample ? tp("example") : tp("hidden")}
                  </span>
                )}
                <span className="flex-1">
                  {notRun ? (
                    <span className="text-xs text-muted-foreground">{t("notRun")}</span>
                  ) : (
                    <Badge variant={verdictVariant(r.verdict)}>{tv(r.verdict)}</Badge>
                  )}
                </span>
                {!notRun && (
                  <span className="font-mono text-xs text-muted-foreground">
                    {formatMs(r.time_ms)} · {formatKb(r.memory_kb)}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

function ReferenceDialog({
  languages,
  initialLanguage,
  initialSource,
  pending,
  error,
  onClose,
  onRun,
}: {
  languages: { key: string; name: string }[];
  initialLanguage: string;
  initialSource: string;
  pending: boolean;
  error: string | null;
  onClose: () => void;
  onRun: (language: string, source: string) => void;
}) {
  const t = useTranslations("challenges.admin.programming.reference");
  const [language, setLanguage] = useState(initialLanguage);
  const [source, setSource] = useState(initialSource);
  const [fileNote, setFileNote] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  async function onFile(file: File) {
    setFileNote(null);
    if (file.size > MAX_SOURCE_BYTES) {
      setFileNote(t("fileTooBig"));
      return;
    }
    try {
      const text = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
      if (text.includes("\u0000")) throw new Error("binary");
      setSource(text);
    } catch {
      setFileNote(t("fileNotText"));
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t("dialogTitle")}</DialogTitle>
          <DialogDescription>{t("dialogDescription")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-48 space-y-1.5">
              <Label htmlFor="reference-language">{t("language")}</Label>
              <Select
                id="reference-language"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
              >
                {languages.map((l) => (
                  <option key={l.key} value={l.key}>
                    {l.name}
                  </option>
                ))}
              </Select>
            </div>
            <Button type="button" variant="outline" onClick={() => fileInput.current?.click()}>
              {t("upload")}
            </Button>
            <input
              ref={fileInput}
              type="file"
              className="sr-only"
              aria-label={t("upload")}
              tabIndex={-1}
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) void onFile(file);
              }}
            />
          </div>
          {fileNote && (
            <p role="alert" className="text-sm text-destructive">
              {fileNote}
            </p>
          )}
          <div className="h-72 overflow-hidden rounded-md border border-input">
            <CodeEditor
              value={source}
              onChange={setSource}
              languageKey={language}
              ariaLabel={t("editorLabel")}
              placeholder={t("placeholder")}
            />
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            type="button"
            disabled={pending || !language || !source.trim()}
            onClick={() => onRun(language, source)}
          >
            {pending ? t("starting") : t("run")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
