"use client";

import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
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
import { Select } from "@/components/ui/select";
import { ReferenceCheckPanel } from "@/components/challenges/reference-check";
import {
  useAddJudgeTestcase,
  useDeleteJudgeTestcase,
  useJudgeProblem,
  useJudgeStatus,
  useJudgeTestcase,
  useUpdateJudgeProblem,
  useUpdateJudgeTestcase,
  useUploadJudgeTestcase,
} from "@/lib/hooks/use-judge";
import type { JudgeCompareMode, JudgeProblem, JudgeTestcase } from "@/lib/types";
import { cn } from "@/lib/utils";

const TEXTAREA =
  "flex w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm text-foreground ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Test cases and judging options for a programming challenge (#447) — the
// editor's counterpart to Attachments/Hints, shown once the challenge exists.
// The common case is just "Add test case" (paste input + expected output); the
// limits, comparison and language overrides sit behind a closed Advanced, each
// blank meaning "use the default" (VISION principle 5).
export function ProgrammingSection({
  competitionId,
  challengeId,
}: {
  competitionId: string;
  challengeId: string;
}) {
  const t = useTranslations("challenges.admin.programming");
  const problem = useJudgeProblem(competitionId, challengeId);
  const remove = useDeleteJudgeTestcase(competitionId, challengeId);
  const confirm = useConfirm();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<JudgeTestcase | null>(null);

  const cases = problem.data?.testcases ?? [];
  const allExamples = cases.length > 0 && cases.every((c) => c.sample);

  return (
    <div className="space-y-3 rounded-md border border-border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <Label>{t("title")}</Label>
          <p className="text-xs text-muted-foreground">{t("description")}</p>
        </div>
        <Button type="button" size="sm" onClick={() => setAdding(true)}>
          {t("add")}
        </Button>
      </div>

      {problem.isError && (
        <p role="alert" className="text-sm text-destructive">
          {(problem.error as Error).message}
        </p>
      )}

      {problem.data && cases.length === 0 && (
        <p className="rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
          {t("empty")}
        </p>
      )}
      {allExamples && (
        <p role="status" className="rounded-md border border-warning/40 bg-warning/15 px-3 py-2 text-sm text-foreground">
          {t("allExamplesWarning")}
        </p>
      )}

      {cases.length > 0 && (
        <ol className="divide-y divide-border rounded-md border border-border">
          {cases.map((c, i) => (
            <li key={c.id} className="flex items-start gap-3 px-3 py-2.5 text-sm">
              <span className="w-6 shrink-0 pt-0.5 text-xs text-muted-foreground">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1 space-y-1">
                <span
                  className={cn(
                    "inline-block rounded-full px-2 py-px text-[11px] font-medium",
                    c.sample ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
                  )}
                >
                  {c.sample ? t("example") : t("hidden")}
                </span>
                <Preview label={t("input")} text={c.input_preview} bytes={c.input_bytes} />
                <Preview label={t("expected")} text={c.answer_preview} bytes={c.answer_bytes} />
              </div>
              <span className="flex shrink-0 gap-1">
                <Button type="button" variant="ghost" size="sm" onClick={() => setEditing(c)}>
                  {t("edit")}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="text-destructive"
                  disabled={remove.isPending}
                  onClick={async () => {
                    if (
                      await confirm({
                        title: t("removeConfirmTitle"),
                        description: t("removeConfirmDescription", { n: i + 1 }),
                        confirmLabel: t("remove"),
                      })
                    ) {
                      remove.mutate(c.id);
                    }
                  }}
                >
                  {t("remove")}
                </Button>
              </span>
            </li>
          ))}
        </ol>
      )}
      {remove.isError && (
        <p role="alert" className="text-sm text-destructive">
          {(remove.error as Error).message}
        </p>
      )}

      {problem.data && cases.length > 0 && (
        <ReferenceCheckPanel
          competitionId={competitionId}
          challengeId={challengeId}
          problem={problem.data}
        />
      )}

      {problem.data && (
        <AdvancedOptions
          // Remount when the saved problem changes so the fields reseed.
          key={JSON.stringify([
            problem.data.time_limit_ms,
            problem.data.memory_limit_mb,
            problem.data.output_limit_kb,
            problem.data.compare_mode,
            problem.data.float_tolerance,
            problem.data.allowed_languages,
          ])}
          competitionId={competitionId}
          challengeId={challengeId}
          problem={problem.data}
        />
      )}

      <AddTestcaseDialog
        open={adding}
        onOpenChange={setAdding}
        competitionId={competitionId}
        challengeId={challengeId}
      />
      {editing && (
        <EditTestcaseDialog
          key={editing.id}
          testcase={editing}
          onClose={() => setEditing(null)}
          competitionId={competitionId}
          challengeId={challengeId}
        />
      )}
    </div>
  );
}

function Preview({ label, text, bytes }: { label: string; text: string; bytes: number }) {
  const t = useTranslations("challenges.admin.programming");
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <span className="w-20 shrink-0 text-xs text-muted-foreground">{label}</span>
      <code className="min-w-0 truncate font-mono text-xs">
        {text.trim() ? text.replace(/\n/g, " ⏎ ") : t("emptyValue")}
      </code>
      {bytes > text.length && (
        <span className="shrink-0 text-xs text-muted-foreground">{formatSize(bytes)}</span>
      )}
    </div>
  );
}

function AddTestcaseDialog({
  open,
  onOpenChange,
  competitionId,
  challengeId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  competitionId: string;
  challengeId: string;
}) {
  const t = useTranslations("challenges.admin.programming");
  const add = useAddJudgeTestcase(competitionId, challengeId);
  const upload = useUploadJudgeTestcase(competitionId, challengeId);
  const [mode, setMode] = useState<"paste" | "upload">("paste");
  const [input, setInput] = useState("");
  const [answer, setAnswer] = useState("");
  const [inputFile, setInputFile] = useState<File | null>(null);
  const [answerFile, setAnswerFile] = useState<File | null>(null);
  const [sample, setSample] = useState(false);
  const pending = add.isPending || upload.isPending;
  const error = (add.error ?? upload.error) as Error | null;

  function close() {
    setInput("");
    setAnswer("");
    setInputFile(null);
    setAnswerFile(null);
    setSample(false);
    add.reset();
    upload.reset();
    onOpenChange(false);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (mode === "paste") {
      add.mutate({ input, answer, sample }, { onSuccess: close });
    } else if (inputFile && answerFile) {
      upload.mutate({ inputFile, answerFile, sample }, { onSuccess: close });
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())}>
      <DialogContent>
        <form onSubmit={onSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{t("addTitle")}</DialogTitle>
            <DialogDescription>{t("addDescription")}</DialogDescription>
          </DialogHeader>

          <div role="tablist" className="flex gap-1 rounded-md bg-muted p-1 text-sm">
            {(["paste", "upload"] as const).map((m) => (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={mode === m}
                onClick={() => setMode(m)}
                className={cn(
                  "flex-1 rounded px-3 py-1.5 transition-colors",
                  mode === m ? "bg-background font-medium shadow-sm" : "text-muted-foreground",
                )}
              >
                {m === "paste" ? t("modePaste") : t("modeUpload")}
              </button>
            ))}
          </div>

          {mode === "paste" ? (
            <>
              <div className="space-y-2">
                <Label htmlFor="tc-input">{t("input")}</Label>
                <textarea
                  id="tc-input"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  rows={5}
                  placeholder={t("inputPlaceholder")}
                  className={TEXTAREA}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="tc-answer">{t("expected")}</Label>
                <textarea
                  id="tc-answer"
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                  rows={4}
                  required
                  placeholder={t("expectedPlaceholder")}
                  className={TEXTAREA}
                />
              </div>
            </>
          ) : (
            <>
              <p className="text-xs text-muted-foreground">{t("uploadHint")}</p>
              <div className="space-y-2">
                <Label htmlFor="tc-input-file">{t("inputFile")}</Label>
                <Input
                  id="tc-input-file"
                  type="file"
                  required
                  onChange={(e) => setInputFile(e.target.files?.[0] ?? null)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="tc-answer-file">{t("expectedFile")}</Label>
                <Input
                  id="tc-answer-file"
                  type="file"
                  required
                  onChange={(e) => setAnswerFile(e.target.files?.[0] ?? null)}
                />
              </div>
            </>
          )}

          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={sample}
              onChange={(e) => setSample(e.target.checked)}
            />
            <span>
              {t("showAsExample")}
              <span className="block text-xs text-muted-foreground">
                {t("showAsExampleHint")}
              </span>
            </span>
          </label>

          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error.message}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={close}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={pending}>
              {pending ? t("saving") : t("addSubmit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function EditTestcaseDialog({
  testcase,
  onClose,
  competitionId,
  challengeId,
}: {
  testcase: JudgeTestcase;
  onClose: () => void;
  competitionId: string;
  challengeId: string;
}) {
  const t = useTranslations("challenges.admin.programming");
  const content = useJudgeTestcase(competitionId, challengeId, testcase.id);
  const update = useUpdateJudgeTestcase(competitionId, challengeId);
  // Null until the author types: an untouched field isn't sent, so opening and
  // saving a case never rewrites data it didn't change.
  const [input, setInput] = useState<string | null>(null);
  const [answer, setAnswer] = useState<string | null>(null);
  const [sample, setSample] = useState(testcase.sample);
  const editable = content.data?.editable ?? false;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    update.mutate(
      {
        id: testcase.id,
        input: {
          sample,
          ...(input !== null ? { input } : {}),
          ...(answer !== null ? { answer } : {}),
        },
      },
      { onSuccess: onClose },
    );
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <form onSubmit={onSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{t("editTitle")}</DialogTitle>
          </DialogHeader>

          {content.isLoading && (
            <p className="text-sm text-muted-foreground">{t("loading")}</p>
          )}
          {content.isError && (
            <p role="alert" className="text-sm text-destructive">
              {(content.error as Error).message}
            </p>
          )}
          {content.data && !editable && (
            <p className="rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
              {t("notEditable")}
            </p>
          )}
          {content.data && editable && (
            <>
              <div className="space-y-2">
                <Label htmlFor="tc-edit-input">{t("input")}</Label>
                <textarea
                  id="tc-edit-input"
                  value={input ?? content.data.input ?? ""}
                  onChange={(e) => setInput(e.target.value)}
                  rows={5}
                  className={TEXTAREA}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="tc-edit-answer">{t("expected")}</Label>
                <textarea
                  id="tc-edit-answer"
                  value={answer ?? content.data.answer ?? ""}
                  onChange={(e) => setAnswer(e.target.value)}
                  rows={4}
                  className={TEXTAREA}
                />
              </div>
            </>
          )}

          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={sample}
              onChange={(e) => setSample(e.target.checked)}
            />
            <span>
              {t("showAsExample")}
              <span className="block text-xs text-muted-foreground">
                {t("showAsExampleHint")}
              </span>
            </span>
          </label>

          {update.isError && (
            <p role="alert" className="text-sm text-destructive">
              {(update.error as Error).message}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={update.isPending || !content.data}>
              {update.isPending ? t("saving") : t("save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Limits, comparison and languages. Every field left blank uses the default,
 *  so most problems never open this. */
function AdvancedOptions({
  competitionId,
  challengeId,
  problem,
}: {
  competitionId: string;
  challengeId: string;
  problem: JudgeProblem;
}) {
  const t = useTranslations("challenges.admin.programming");
  const status = useJudgeStatus(competitionId);
  const update = useUpdateJudgeProblem(competitionId, challengeId);
  const asText = (v: number | null) => (v == null ? "" : String(v));
  const [timeLimit, setTimeLimit] = useState(asText(problem.time_limit_ms));
  const [memoryLimit, setMemoryLimit] = useState(asText(problem.memory_limit_mb));
  const [outputLimit, setOutputLimit] = useState(asText(problem.output_limit_kb));
  const [compare, setCompare] = useState<JudgeCompareMode>(problem.compare_mode);
  const [tolerance, setTolerance] = useState(asText(problem.float_tolerance));
  const [allLanguages, setAllLanguages] = useState(problem.allowed_languages === null);
  const [languages, setLanguages] = useState<string[]>(problem.allowed_languages ?? []);
  const available = status.data?.languages ?? [];
  const [saved, setSaved] = useState(false);

  const toNumber = (v: string) => (v.trim() === "" ? null : Number(v));

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSaved(false);
    update.mutate(
      {
        time_limit_ms: toNumber(timeLimit),
        memory_limit_mb: toNumber(memoryLimit),
        output_limit_kb: toNumber(outputLimit),
        compare_mode: compare,
        float_tolerance: compare === "float" ? toNumber(tolerance) : null,
        allowed_languages: allLanguages ? null : languages,
      },
      { onSuccess: () => setSaved(true) },
    );
  }

  return (
    <details className="rounded-md border border-border">
      <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium">
        {t("advanced")}
        <span className="ml-2 text-xs font-normal text-muted-foreground">
          {t("advancedHint")}
        </span>
      </summary>
      <form onSubmit={onSubmit} className="grid gap-4 border-t border-border p-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <LimitField
            id="judge-time"
            label={t("timeLimit")}
            value={timeLimit}
            onChange={setTimeLimit}
            placeholder={t("defaultValue", { value: problem.default_time_limit_ms })}
            min={100}
            max={60000}
          />
          <LimitField
            id="judge-memory"
            label={t("memoryLimit")}
            value={memoryLimit}
            onChange={setMemoryLimit}
            placeholder={t("defaultValue", { value: problem.default_memory_limit_mb })}
            min={16}
            max={8192}
          />
          <LimitField
            id="judge-output"
            label={t("outputLimit")}
            value={outputLimit}
            onChange={setOutputLimit}
            placeholder={t("defaultValue", { value: problem.default_output_limit_kb })}
            min={1}
            max={262144}
          />
        </div>
        <p className="-mt-2 text-xs text-muted-foreground">{t("limitsHint")}</p>

        <div className="space-y-2">
          <Label htmlFor="judge-compare">{t("compare")}</Label>
          <Select
            id="judge-compare"
            value={compare}
            onChange={(e) => setCompare(e.target.value as JudgeCompareMode)}
            className="max-w-md"
          >
            <option value="token">{t("compareToken")}</option>
            <option value="exact">{t("compareExact")}</option>
            <option value="float">{t("compareFloat")}</option>
          </Select>
          {compare === "float" && (
            <div className="flex items-center gap-2">
              <Label htmlFor="judge-tolerance" className="shrink-0 text-xs font-normal">
                {t("tolerance")}
              </Label>
              <Input
                id="judge-tolerance"
                type="number"
                step="any"
                min={0}
                max={1}
                value={tolerance}
                onChange={(e) => setTolerance(e.target.value)}
                placeholder="0.000001"
                className="max-w-[10rem]"
              />
            </div>
          )}
        </div>

        <div className="space-y-2">
          <Label>{t("languages")}</Label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={allLanguages}
              onChange={(e) => setAllLanguages(e.target.checked)}
            />
            {t("allLanguages")}
          </label>
          {!allLanguages && (
            <div className="flex flex-wrap gap-x-4 gap-y-1.5 pl-6">
              {available.length === 0 && (
                <span className="text-xs text-muted-foreground">{t("noLanguages")}</span>
              )}
              {available.map((lang) => (
                <label key={lang.key} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={languages.includes(lang.key)}
                    onChange={(e) =>
                      setLanguages((prev) =>
                        e.target.checked
                          ? [...prev, lang.key]
                          : prev.filter((k) => k !== lang.key),
                      )
                    }
                  />
                  {lang.name}
                </label>
              ))}
            </div>
          )}
        </div>

        {update.isError && (
          <p role="alert" className="text-sm text-destructive">
            {(update.error as Error).message}
          </p>
        )}
        <div className="flex items-center gap-3">
          <Button type="submit" size="sm" disabled={update.isPending}>
            {update.isPending ? t("saving") : t("saveOptions")}
          </Button>
          {saved && <span className="text-sm text-muted-foreground">{t("savedOptions")}</span>}
        </div>
      </form>
    </details>
  );
}

function LimitField({
  id,
  label,
  value,
  onChange,
  placeholder,
  min,
  max,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  min: number;
  max: number;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-xs">
        {label}
      </Label>
      <Input
        id={id}
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}
