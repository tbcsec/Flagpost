"use client";

import { useTranslations } from "next-intl";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useMemo, useRef, useState, type DragEvent } from "react";

import { ChallengeFiles } from "@/components/challenges/challenge-files";
import { ChallengeValue } from "@/components/challenges/challenge-value";
import {
  ClarificationsLink,
  ProblemClarifications,
} from "@/components/challenges/problem-clarifications";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm";
import { Label } from "@/components/ui/label";
import { RichTextView } from "@/components/ui/rich-text-view";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import { useCategories } from "@/lib/hooks/use-categories";
import { useChallenge, useChallenges } from "@/lib/hooks/use-challenges";
import {
  useLoadJudgingSource,
  useMyJudgings,
  useProblemView,
  useSubmitCode,
} from "@/lib/hooks/use-judge";
import type {
  Challenge,
  CodeSubmitInput,
  Judging,
  JudgingRun,
  ProblemView,
} from "@/lib/types";
import { cn } from "@/lib/utils";

// The editor is CodeMirror — loaded only here, client-side, so it stays out of
// every other route's bundle (as the collaborative TipTap editor is).
const CodeEditor = dynamic(
  () => import("@/components/challenges/code-editor").then((m) => m.CodeEditor),
  { ssr: false, loading: () => <Skeleton className="h-72 w-full" /> },
);

// --- the draft, kept per problem in this browser ---------------------------------------

interface Draft {
  language: string;
  // Source per language, so switching languages doesn't lose work.
  sources: Record<string, string>;
}

const draftKey = (competitionId: string, challengeId: string) =>
  `flagpost.code.${competitionId}.${challengeId}`;

function readDraft(key: string): Draft | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(key);
    const parsed = raw ? (JSON.parse(raw) as Draft) : null;
    return parsed && typeof parsed.sources === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function writeDraft(key: string, draft: Draft) {
  try {
    window.localStorage.setItem(key, JSON.stringify(draft));
  } catch {
    // Private mode / quota: the draft just isn't kept.
  }
}

// --- formatting ------------------------------------------------------------------------

const formatMs = (ms: number | null | undefined) => (ms == null ? "—" : `${ms} ms`);

// --- loading a saved file --------------------------------------------------------------

// The server's source cap (routers/judge_submissions.MAX_SOURCE_BYTES).
const MAX_SOURCE_BYTES = 128 * 1024;
// Other spellings of the extensions languages are configured with.
const EXTENSION_ALIASES: Record<string, string> = {
  ".cc": ".cpp",
  ".cxx": ".cpp",
  ".c++": ".cpp",
  ".hpp": ".cpp",
  ".mjs": ".js",
  ".cjs": ".js",
  ".pyw": ".py",
};

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  const ext = dot >= 0 ? name.slice(dot).toLowerCase() : "";
  return EXTENSION_ALIASES[ext] ?? ext;
}

/** The language for a file: one whose extension matches, preferring the one
 *  already chosen (Python 3 and PyPy both save as .py). Null if none does. */
export function languageForFile(
  name: string,
  languages: { key: string; extension: string }[],
  current: string,
): string | null {
  const ext = extensionOf(name);
  const matches = languages.filter((l) => l.extension === ext);
  if (matches.length === 0) return null;
  return matches.some((l) => l.key === current) ? current : matches[0].key;
}

type FileProblem = "tooBig" | "notText" | "unreadable";

async function readCodeFile(file: File): Promise<string | FileProblem> {
  if (file.size > MAX_SOURCE_BYTES) return "tooBig";
  let bytes: ArrayBuffer;
  try {
    bytes = await file.arrayBuffer();
  } catch {
    return "unreadable"; // permissions, a file that moved, a sandboxed browser
  }
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    return text.includes("\u0000") ? "notText" : text;
  } catch {
    return "notText";
  }
}
const formatKb = (kb: number | null | undefined) =>
  kb == null ? "—" : kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb} KB`;

const VERDICT_TONE: Record<string, string> = {
  accepted: "border-success/45 bg-success/10 text-success",
  internal_error: "border-border bg-muted text-muted-foreground",
};
const verdictTone = (verdict: string | null) =>
  (verdict && VERDICT_TONE[verdict]) || "border-destructive/45 bg-destructive/10 text-destructive";

export function ProgrammingChallenge({
  competitionId,
  challengeId,
}: {
  competitionId: string;
  challengeId: string;
}) {
  const t = useTranslations("challenges.code");
  const challenge = useChallenge(competitionId, challengeId);
  const problem = useProblemView(competitionId, challengeId);

  if (challenge.isLoading || problem.isLoading) {
    return (
      <div className="grid gap-6 lg:grid-cols-2">
        <Skeleton className="h-96 w-full" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }
  const error = (challenge.error ?? problem.error) as Error | null;
  if (error || !challenge.data || !problem.data) {
    return (
      <div className="space-y-3">
        <BackLink />
        <p role="alert" className="text-sm text-destructive">
          {error?.message ?? t("notFound")}
        </p>
      </div>
    );
  }
  if (challenge.data.flag_type !== "programming") {
    return (
      <div className="space-y-3">
        <BackLink />
        <p className="text-sm text-muted-foreground">{t("notProgramming")}</p>
      </div>
    );
  }
  return (
    <Solver competitionId={competitionId} challenge={challenge.data} problem={problem.data} />
  );
}

function BackLink() {
  const t = useTranslations("challenges.code");
  return (
    <Link href="/challenges" className="text-sm text-muted-foreground hover:text-foreground">
      ← {t("back")}
    </Link>
  );
}

type Mode = "upload" | "write";
const MODE_KEY = "flagpost.code.mode";

function readMode(): Mode {
  if (typeof window === "undefined") return "upload";
  try {
    return window.localStorage.getItem(MODE_KEY) === "write" ? "write" : "upload";
  } catch {
    return "upload";
  }
}

interface LoadedFile {
  name: string;
  content: string;
  lines: number;
  bytes: number;
}

function Solver({
  competitionId,
  challenge,
  problem,
}: {
  competitionId: string;
  challenge: Challenge;
  problem: ProblemView;
}) {
  const t = useTranslations("challenges.code");
  const categories = useCategories(competitionId);
  const all = useChallenges(competitionId);
  const judgings = useMyJudgings(competitionId, challenge.id);
  const submit = useSubmitCode(competitionId, challenge.id);
  const loadSource = useLoadJudgingSource(competitionId);
  const confirm = useConfirm();

  const key = draftKey(competitionId, challenge.id);
  const languages = problem.languages;
  const [draft, setDraft] = useState<Draft>(() => {
    const saved = readDraft(key);
    const language =
      saved && languages.some((l) => l.key === saved.language) ? saved.language : (languages[0]?.key ?? "");
    return { language, sources: saved?.sources ?? {} };
  });
  // Uploading a file (the default, and most participants' way) or writing in
  // the browser; the choice is remembered across problems.
  const [mode, setModeState] = useState<Mode>(readMode);
  const [uploaded, setUploaded] = useState<LoadedFile | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [fileNote, setFileNote] = useState<{ text: string; problem: boolean } | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const setMode = (next: Mode) => {
    setModeState(next);
    setFileNote(null);
    try {
      window.localStorage.setItem(MODE_KEY, next);
    } catch {
      // The preference just isn't kept.
    }
  };
  const update = useCallback(
    (next: Draft) => {
      setDraft(next);
      writeDraft(key, next);
    },
    [key],
  );
  const onSourceChange = useCallback(
    (value: string) =>
      setDraft((prev) => {
        const next = { ...prev, sources: { ...prev.sources, [prev.language]: value } };
        writeDraft(key, next);
        return next;
      }),
    [key],
  );

  // What Run / Submit send: exactly the uploaded file, or the editor's code.
  const source = mode === "upload" ? (uploaded?.content ?? "") : (draft.sources[draft.language] ?? "");
  const list = judgings.data ?? [];
  const shown = (selected && list.find((j) => j.id === selected)) || list[0] || null;
  const category = categories.data?.find((c) => c.id === challenge.category_id)?.name;
  const lockedBy = useMemo(
    () =>
      challenge.locked
        ? (all.data ?? [])
            .filter((c) => challenge.prerequisites.includes(c.id) && !c.solved)
            .map((c) => c.title)
        : [],
    [all.data, challenge],
  );
  const language = languages.find((l) => l.key === draft.language);
  const canSubmit =
    problem.judge_ready && !challenge.locked && !!language && source.trim() !== "" && !submit.isPending;
  const extensions = [...new Set(languages.map((l) => l.extension).filter(Boolean))];

  /** Read and check a file; on a problem, say what's wrong and return null. */
  async function readFile(file: File): Promise<{ content: string; detected: string | null } | null> {
    const content = await readCodeFile(file);
    if (content === "tooBig") {
      setFileNote({ text: t("uploadTooBig", { kb: MAX_SOURCE_BYTES / 1024 }), problem: true });
      return null;
    }
    if (content === "notText" || content === "unreadable") {
      setFileNote({
        text: t(content === "notText" ? "uploadNotText" : "uploadUnreadable"),
        problem: true,
      });
      return null;
    }
    const detected = languageForFile(file.name, languages, draft.language);
    setFileNote(
      detected
        ? { text: t("uploadLoaded", { name: file.name }), problem: false }
        : { text: t("uploadUnknownType", { name: file.name }), problem: true },
    );
    return { content, detected };
  }

  async function chooseUpload(file: File) {
    const read = await readFile(file);
    if (!read) return;
    setUploaded({
      name: file.name,
      content: read.content,
      lines: read.content.split("\n").length - (read.content.endsWith("\n") ? 1 : 0),
      bytes: file.size,
    });
    if (read.detected) update({ ...draft, language: read.detected });
  }

  async function dropIntoEditor(file: File) {
    const read = await readFile(file);
    if (!read) return;
    const target = read.detected ?? draft.language;
    update({ language: target, sources: { ...draft.sources, [target]: read.content } });
  }

  function editInBrowser() {
    if (!uploaded) return;
    update({ ...draft, sources: { ...draft.sources, [draft.language]: uploaded.content } });
    setMode("write");
  }

  const isFileDrag = (e: DragEvent) => Array.from(e.dataTransfer.types).includes("Files");
  const dragHandlers = (onFile: (file: File) => void) => ({
    onDragOver: (e: DragEvent<HTMLDivElement>) => {
      if (!isFileDrag(e)) return;
      e.preventDefault();
      setDragging(true);
    },
    onDragLeave: () => setDragging(false),
    onDrop: (e: DragEvent<HTMLDivElement>) => {
      if (!isFileDrag(e)) return;
      // Stopped here, before CodeMirror would insert the file's text at the
      // drop point: a dropped file replaces the code (and picks the language).
      e.preventDefault();
      e.stopPropagation();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) onFile(file);
    },
  });
  const uploadDrag = dragHandlers((f) => void chooseUpload(f));
  const editorDrag = dragHandlers((f) => void dropIntoEditor(f));

  function send(kind: CodeSubmitInput["kind"]) {
    setSelected(null);
    setFileNote(null);
    submit.mutate({ language: draft.language, source, kind });
  }

  async function onLoadSource(judging: Judging) {
    const current = draft.sources[judging.language_key] ?? "";
    if (
      current.trim() !== "" &&
      !(await confirm({
        title: t("loadConfirmTitle"),
        description: t("loadConfirmDescription"),
        confirmLabel: t("loadConfirmLabel"),
        destructive: false,
      }))
    ) {
      return;
    }
    loadSource.mutate(judging.id, {
      onSuccess: ({ language_key, source: code }) => {
        update({ language: language_key, sources: { ...draft.sources, [language_key]: code } });
        setMode("write");
      },
    });
  }

  const problemBlocked = languages.length === 0 || !problem.judge_ready;

  return (
    <div className="space-y-6">
      {/* The problem, full width. */}
      <div className="space-y-4">
        <BackLink />
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">{challenge.title}</h1>
            {challenge.solved && <Badge variant="success">{t("solved")}</Badge>}
          </div>
          <p className="text-sm text-muted-foreground">
            {category ? `${category} · ` : ""}
            <ChallengeValue challenge={challenge} /> · {t("solves", { count: challenge.solve_count })}
            {" · "}
            {t("limits", {
              seconds: (language?.time_limit_ms ?? problem.time_limit_ms) / 1000,
              memory: problem.memory_limit_mb,
            })}
            <ClarificationsLink competitionId={competitionId} challengeId={challenge.id} />
          </p>
        </div>
        {lockedBy.length > 0 && (
          <p className="rounded-md border border-warning/40 bg-warning/15 px-3 py-2 text-sm text-foreground">
            {t("locked", { titles: lockedBy.join(", ") })}
          </p>
        )}
        <Card>
          <CardContent className="grid gap-6 pt-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <div className="min-w-0">
              {challenge.description && Object.keys(challenge.description).length > 0 ? (
                <RichTextView value={challenge.description} className="leading-relaxed" />
              ) : (
                <p className="text-sm text-muted-foreground">{t("noStatement")}</p>
              )}
              <ChallengeFiles competitionId={competitionId} challengeId={challenge.id} />
              {/* The judges' clarifications amend the statement, so they close it. */}
              <ProblemClarifications
                competitionId={competitionId}
                challengeId={challenge.id}
                challengeTitle={challenge.title}
              />
            </div>
            {problem.examples.length > 0 && (
              <div className="min-w-0 space-y-3 lg:border-l lg:border-border lg:pl-6">
                <h2 className="text-sm font-semibold">{t("examples")}</h2>
                {problem.examples.map((ex) => (
                  <div key={ex.index} className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
                    <IoBlock label={t("exampleInput", { n: ex.index + 1 })} text={ex.input} />
                    <IoBlock label={t("exampleOutput", { n: ex.index + 1 })} text={ex.answer} />
                    {ex.truncated && (
                      <p className="text-xs text-muted-foreground sm:col-span-2 lg:col-span-1 xl:col-span-2">
                        {t("exampleTruncated")}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Your solution, full width: upload a file (the main way) or write it here. */}
      <Card>
        <CardHeader className="space-y-3 pb-0">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <CardTitle>{t("solutionTitle")}</CardTitle>
            <div className="flex items-center gap-2">
              <Label htmlFor="code-language" className="text-sm text-muted-foreground">
                {t("language")}
              </Label>
              <Select
                id="code-language"
                value={draft.language}
                onChange={(e) => update({ ...draft, language: e.target.value })}
                className="h-9 w-auto min-w-[9rem]"
              >
                {languages.map((l) => (
                  <option key={l.key} value={l.key}>
                    {l.name}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <Tabs
            tabs={[
              { value: "upload", label: t("tabUpload") },
              { value: "write", label: t("tabWrite") },
            ]}
            value={mode}
            onValueChange={(v) => setMode(v as Mode)}
          />
        </CardHeader>
        <CardContent className="space-y-4 pt-5">
          <input
            ref={fileInput}
            type="file"
            className="hidden"
            aria-label={t("chooseFile")}
            accept={[...new Set([...extensions, ...Object.keys(EXTENSION_ALIASES)])].join(",")}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) void chooseUpload(file);
            }}
          />

          {mode === "upload" ? (
            <div
              {...uploadDrag}
              className={cn(
                "flex min-h-[11rem] flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed px-6 py-8 text-center transition-colors",
                dragging ? "border-primary bg-primary/5" : "border-border",
              )}
            >
              {uploaded ? (
                <>
                  <FileIcon className="h-8 w-8 text-primary" />
                  <div>
                    <p className="font-mono text-base font-medium">{uploaded.name}</p>
                    <p className="text-sm text-muted-foreground">
                      {t("fileSummary", {
                        language: language?.name ?? draft.language,
                        lines: uploaded.lines,
                        kb: Math.max(0.1, Math.round(uploaded.bytes / 102.4) / 10),
                      })}
                    </p>
                  </div>
                  <div className="flex flex-wrap justify-center gap-2">
                    <Button type="button" variant="outline" onClick={() => fileInput.current?.click()}>
                      {t("chooseAnother")}
                    </Button>
                    <Button type="button" variant="ghost" onClick={editInBrowser}>
                      {t("editInBrowser")}
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <UploadIcon className="h-9 w-9 text-muted-foreground" />
                  <div className="space-y-1">
                    <p className="text-base font-medium">{dragging ? t("dropToLoad") : t("dropTitle")}</p>
                    {extensions.length > 0 && (
                      <p className="text-sm text-muted-foreground">
                        {t("dropHint", { extensions: extensions.join(", ") })}
                      </p>
                    )}
                  </div>
                  <Button type="button" size="lg" onClick={() => fileInput.current?.click()}>
                    {t("chooseFile")}
                  </Button>
                </>
              )}
            </div>
          ) : (
            <div
              {...editorDrag}
              onDragOverCapture={editorDrag.onDragOver}
              onDropCapture={editorDrag.onDrop}
              className={cn(
                "relative h-[26rem] overflow-hidden rounded-lg border border-border lg:h-[34rem]",
                dragging && "ring-2 ring-primary",
              )}
            >
              {dragging && (
                <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center bg-background/80 text-sm font-medium">
                  {t("dropToLoad")}
                </div>
              )}
              <CodeEditor
                value={draft.sources[draft.language] ?? ""}
                onChange={onSourceChange}
                languageKey={draft.language}
                ariaLabel={t("editorLabel")}
                placeholder={t("editorPlaceholder")}
              />
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-h-[1.25rem] text-sm" aria-live="polite">
              {problemBlocked ? (
                <p role="alert" className="text-destructive">
                  {languages.length === 0 ? t("noLanguages") : t("judgeDown")}
                </p>
              ) : submit.isError ? (
                <p role="alert" className="text-destructive">
                  {(submit.error as Error).message}
                </p>
              ) : fileNote ? (
                <p role={fileNote.problem ? "alert" : "status"} className={fileNote.problem ? "text-destructive" : "text-muted-foreground"}>
                  {fileNote.text}
                </p>
              ) : mode === "upload" && !uploaded ? (
                <p className="text-muted-foreground">{t("chooseFirst")}</p>
              ) : null}
            </div>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="lg"
                className="px-5"
                onClick={() => send("run")}
                disabled={!canSubmit || problem.examples.length === 0}
                title={problem.examples.length === 0 ? t("runNoExamples") : t("runHint")}
              >
                {t("run")}
              </Button>
              <Button type="button" size="lg" className="px-6" onClick={() => send("submit")} disabled={!canSubmit}>
                {submit.isPending ? t("sending") : t("submit")}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* The latest result beside the history. */}
      {list.length > 0 && (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] lg:items-start">
          <div className="min-w-0">{shown && <VerdictPanel judging={shown} problem={problem} />}</div>
          <Card className="min-w-0">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">{t("history")}</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <ul className="max-h-96 divide-y divide-border overflow-y-auto border-t border-border">
                {list.map((j) => (
                  <li key={j.id} className="flex items-center gap-2 px-4 py-2 text-sm">
                    <button
                      type="button"
                      onClick={() => setSelected(j.id)}
                      aria-current={shown?.id === j.id ? "true" : undefined}
                      className={cn(
                        "flex min-w-0 flex-1 items-center gap-2 text-left",
                        shown?.id === j.id && "font-medium",
                      )}
                    >
                      <span className="w-14 shrink-0 text-xs uppercase tracking-wide text-muted-foreground">
                        {j.kind === "run" ? t("kindRun") : t("kindSubmit")}
                      </span>
                      <span className="truncate">{j.language_name}</span>
                      {j.origin !== "submission" && (
                        <span className="shrink-0 text-[11px] text-muted-foreground">
                          {j.origin === "rejudge" ? t("originRejudge") : t("originOverride")}
                        </span>
                      )}
                      <span className="ml-auto shrink-0">
                        <StatusChip judging={j} />
                      </span>
                    </button>
                    {j.kind === "submit" && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => onLoadSource(j)}
                        disabled={loadSource.isPending}
                      >
                        {t("loadCode")}
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

function UploadIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      <path d="M12 16V4" />
      <path d="m7 9 5-5 5 5" />
      <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
    </svg>
  );
}

function FileIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
      <path d="m10 13-2 2 2 2" />
      <path d="m14 13 2 2-2 2" />
    </svg>
  );
}

function IoBlock({ label, text }: { label: string; text: string }) {
  return (
    <div className="min-w-0 space-y-1">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <pre className="max-h-48 overflow-auto rounded-md border border-border bg-muted/40 px-3 py-2 font-mono text-xs leading-relaxed">
        {text}
      </pre>
    </div>
  );
}

function StatusChip({ judging }: { judging: Judging }) {
  const t = useTranslations("challenges.code");
  if (judging.status === "queued" || judging.status === "running") {
    return (
      <span className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">
        {judging.status === "queued" ? t("statusQueued") : t("statusRunning")}
      </span>
    );
  }
  return (
    <span className={cn("rounded-full border px-2 py-0.5 text-xs", verdictTone(judging.verdict))}>
      {t(`verdict.${judging.verdict ?? "internal_error"}`)}
    </span>
  );
}

function VerdictPanel({ judging, problem }: { judging: Judging; problem: ProblemView }) {
  const t = useTranslations("challenges.code");
  const active = judging.status === "queued" || judging.status === "running";
  const failing = judging.tests.find((r) => r.verdict !== "accepted") ?? null;

  return (
    <Card aria-live="polite">
      <CardContent className="space-y-3 pt-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm text-muted-foreground">
            {judging.kind === "run" ? t("resultRun") : t("resultSubmit")} · {judging.language_name}
            {judging.origin === "rejudge" && ` · ${t("originRejudge")}`}
            {judging.origin === "override" && ` · ${t("originOverride")}`}
          </div>
          {!active && judging.tests_total != null && judging.verdict !== "compile_error" && (
            <div className="text-xs text-muted-foreground">
              {t("passed", { passed: judging.tests_passed ?? 0, total: judging.tests_total })}
              {judging.max_time_ms != null && ` · ${formatMs(judging.max_time_ms)}`}
              {judging.max_memory_kb != null && ` · ${formatKb(judging.max_memory_kb)}`}
            </div>
          )}
        </div>

        {active ? (
          <p className="flex items-center gap-2 text-base font-medium">
            <span className="h-2 w-2 animate-pulse rounded-full bg-primary" aria-hidden="true" />
            {judging.status === "queued"
              ? judging.queue_position && judging.queue_position > 1
                ? t("queuedAt", { position: judging.queue_position })
                : t("queuedNext")
              : t("running")}
          </p>
        ) : (
          <div className={cn("rounded-md border px-3 py-2", verdictTone(judging.verdict))}>
            <div className="text-base font-semibold">
              {t(`verdict.${judging.verdict ?? "internal_error"}`)}
            </div>
            <div className="text-sm opacity-90">
              {t(`verdictHint.${judging.verdict ?? "internal_error"}`)}
            </div>
          </div>
        )}

        {judging.compile_output && (
          <details open={judging.verdict === "compile_error"}>
            <summary className="cursor-pointer text-sm font-medium">{t("compilerOutput")}</summary>
            <pre className="mt-2 max-h-56 overflow-auto rounded-md border border-border bg-muted/40 px-3 py-2 font-mono text-xs">
              {judging.compile_output}
            </pre>
          </details>
        )}

        {failing && <FailingTest run={failing} problem={problem} />}

        {judging.tests.length > 0 && (
          <ol className="flex flex-wrap gap-1.5" aria-label={t("tests")}>
            {judging.tests.map((r) => (
              <li
                key={r.index}
                title={`${r.sample ? t("exampleN", { n: r.index + 1 }) : t("hiddenN", { n: r.index + 1 })}: ${t(`verdict.${r.verdict}`)}`}
                className={cn(
                  "rounded border px-1.5 py-0.5 font-mono text-[11px]",
                  r.verdict === "accepted" ? VERDICT_TONE.accepted : verdictTone(r.verdict),
                )}
              >
                {r.index + 1}
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

/** The first test that didn't pass. An example shows its input, the expected
 *  output and the program's own; a hidden test only which one it was — its
 *  data stays hidden. */
function FailingTest({ run, problem }: { run: JudgingRun; problem: ProblemView }) {
  const t = useTranslations("challenges.code");
  const example = run.sample ? problem.examples.find((e) => e.index === run.index) : undefined;
  if (!run.sample || !example) {
    return (
      <p className="text-sm">
        {t("failedHidden", { n: run.index + 1, verdict: t(`verdict.${run.verdict}`) })}
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-sm">
        {t("failedExample", { n: run.index + 1, verdict: t(`verdict.${run.verdict}`) })}
      </p>
      <div className="grid gap-2 sm:grid-cols-3">
        <IoBlock label={t("input")} text={example.input} />
        <IoBlock label={t("expected")} text={example.answer} />
        <IoBlock label={t("yourOutput")} text={run.output ?? ""} />
      </div>
    </div>
  );
}
