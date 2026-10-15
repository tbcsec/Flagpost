"use client";

// Problem packages (#451): import the open ICPC/Kattis problem package format
// — one problem or a contest zip of several — as draft programming
// challenges, and export them back out. Problems Flagpost can't judge
// faithfully (their own output checker, interactive, scored…) are refused
// with the reason; everything imported arrives as a draft, with a short list
// of what to check before publishing.

import { useTranslations } from "next-intl";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useExportProblemPackages,
  useImportProblemPackages,
  useJudgeStatus,
} from "@/lib/hooks/use-judge";
import type { PackageImportResult } from "@/lib/types";
import { toast } from "@/stores/toast";

export function ProblemPackageActions({
  competitionId,
  hasProgramming,
  onOpen,
}: {
  competitionId: string;
  hasProgramming: boolean;
  /** Open an imported problem in the editor. */
  onOpen: (challengeId: string) => void;
}) {
  const t = useTranslations("challenges.admin.packages");
  const status = useJudgeStatus(competitionId);
  const exportAll = useExportProblemPackages(competitionId);
  const [open, setOpen] = useState(false);

  if (!status.data?.module_enabled) return null;

  return (
    <div className="flex items-center gap-2">
      <Button variant="outline" size="sm" className="flex-1" onClick={() => setOpen(true)}>
        {t("import")}
      </Button>
      {hasProgramming && (
        <Button
          variant="outline"
          size="sm"
          className="flex-1"
          disabled={exportAll.isPending}
          onClick={() =>
            exportAll.mutate(undefined, {
              onError: (err) =>
                toast(t("exportFailed"), { description: (err as Error).message, variant: "destructive" }),
            })
          }
        >
          {t("exportAll")}
        </Button>
      )}
      {open && (
        <ImportDialog
          competitionId={competitionId}
          defaultSeconds={(status.data.default_time_limit_ms ?? 2000) / 1000}
          onClose={() => setOpen(false)}
          onOpen={(id) => {
            setOpen(false);
            onOpen(id);
          }}
        />
      )}
    </div>
  );
}

function ImportDialog({
  competitionId,
  defaultSeconds,
  onClose,
  onOpen,
}: {
  competitionId: string;
  defaultSeconds: number;
  onClose: () => void;
  onOpen: (challengeId: string) => void;
}) {
  const t = useTranslations("challenges.admin.packages");
  const importPackages = useImportProblemPackages(competitionId);
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [seconds, setSeconds] = useState(String(defaultSeconds));
  const [result, setResult] = useState<PackageImportResult | null>(null);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    const value = Number(seconds);
    importPackages.mutate(
      {
        file,
        defaultTimeLimitMs: seconds.trim() && Number.isFinite(value) ? Math.round(value * 1000) : null,
      },
      { onSuccess: setResult },
    );
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        {result ? (
          <ImportReport result={result} onOpen={onOpen} />
        ) : (
          <form id="package-import" onSubmit={onSubmit} className="grid gap-4">
            <div className="grid gap-1.5">
              <Label htmlFor="package-file">{t("file")}</Label>
              <div className="flex flex-wrap items-center gap-2">
                <Button type="button" variant="outline" size="sm" onClick={() => fileInput.current?.click()}>
                  {t("chooseFile")}
                </Button>
                <span className="text-sm text-muted-foreground">{file ? file.name : t("noFile")}</span>
              </div>
              <input
                ref={fileInput}
                id="package-file"
                type="file"
                accept=".zip,.kpp,application/zip"
                className="sr-only"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="package-time-limit">{t("timeLimit")}</Label>
              <Input
                id="package-time-limit"
                type="number"
                step="any"
                min={0.1}
                max={60}
                value={seconds}
                onChange={(e) => setSeconds(e.target.value)}
                className="max-w-[8rem]"
              />
              <p className="text-xs text-muted-foreground">{t("timeLimitHint")}</p>
            </div>
            {importPackages.isError && (
              <p role="alert" className="text-sm text-destructive">
                {(importPackages.error as Error).message}
              </p>
            )}
          </form>
        )}
        <DialogFooter>
          {result ? (
            <>
              <Button type="button" variant="outline" onClick={() => setResult(null)}>
                {t("importAnother")}
              </Button>
              <Button type="button" onClick={onClose}>
                {t("done")}
              </Button>
            </>
          ) : (
            <>
              <Button type="button" variant="outline" onClick={onClose}>
                {t("cancel")}
              </Button>
              <Button type="submit" form="package-import" disabled={!file || importPackages.isPending}>
                {importPackages.isPending ? t("importing") : t("importButton")}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ImportReport({
  result,
  onOpen,
}: {
  result: PackageImportResult;
  onOpen: (challengeId: string) => void;
}) {
  const t = useTranslations("challenges.admin.packages");
  return (
    <div className="grid gap-4" aria-live="polite">
      <p className="text-sm font-medium">
        {result.created.length > 0
          ? t("createdCount", { count: result.created.length })
          : t("nothingCreated")}
      </p>
      {result.created.length > 0 && (
        <ul className="grid gap-2">
          {result.created.map((c) => (
            <li key={c.challenge_id} className="rounded-md border border-border px-3 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <button
                  type="button"
                  className="text-left text-sm font-medium text-primary underline-offset-4 hover:underline"
                  onClick={() => onOpen(c.challenge_id)}
                >
                  {c.name}
                </button>
                <span className="text-xs text-muted-foreground">{t("tests", { count: c.tests })}</span>
              </div>
              {c.warnings.length > 0 && (
                <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
                  {c.warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
      {result.refused.length > 0 && (
        <div className="grid gap-1.5">
          <p className="text-sm font-medium">{t("refusedTitle")}</p>
          <ul className="grid gap-1 text-sm">
            {result.refused.map((r) => (
              <li key={r.name} className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2">
                <span className="font-medium">{r.name}</span> — {r.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
      {result.skipped.length > 0 && (
        <div className="grid gap-1.5">
          <p className="text-sm font-medium">{t("skippedTitle")}</p>
          <ul className="grid gap-1 text-sm text-muted-foreground">
            {result.skipped.map((s) => (
              <li key={s.name}>
                {s.name} — {s.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
