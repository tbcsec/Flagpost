"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import { Skeleton } from "@/components/ui/skeleton";
import {
  useCreateJudgeLanguage,
  useDeleteJudgeLanguage,
  useJudgeLanguagePresets,
  useJudgeLanguages,
  useJudgeSettings,
  useUpdateJudgeLanguage,
  useUpdateJudgeSettings,
} from "@/lib/hooks/use-judge";
import type { JudgeLanguage, JudgeLanguagePreset, JudgeSettings } from "@/lib/types";
import { toast } from "@/stores/toast";

// Admin → Site settings → Code judge (#446, ADR-0042). The site-wide judge
// config: the container-runtime endpoint (a least-privilege socket proxy, as
// for instancing), how many judgings run at once, the default limits a problem
// inherits, and the language registry — a stock image plus argv commands per
// language. The judge ships inert: it can only be enabled once an endpoint and
// at least one enabled language exist, mirrored here for instant feedback.

const TEXTAREA_CLASS =
  "flex min-h-[72px] w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

function clamp(value: string, lo: number, hi: number, fallback: number): number {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(hi, Math.max(lo, n));
}

/** One argv argument per line — an argument containing spaces stays whole,
 *  which a space-split single field couldn't express. Blank lines drop. */
function linesToArgv(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function argvToLines(argv: string[] | null): string {
  return (argv ?? []).join("\n");
}

export function JudgeSettingsPanel() {
  const settings = useJudgeSettings();
  const languages = useJudgeLanguages();
  const presets = useJudgeLanguagePresets();
  const [nonce, setNonce] = useState(0);
  if (settings.isLoading || !settings.data || languages.isLoading || presets.isLoading) {
    return <Skeleton className="h-64 w-full" />;
  }
  const langs = languages.data ?? [];
  return (
    <div className="grid max-w-3xl gap-5">
      <JudgeSettingsForm
        key={nonce}
        data={settings.data}
        enabledLanguageCount={langs.filter((l) => l.enabled).length}
        onSaved={() => setNonce((n) => n + 1)}
      />
      <LanguagesCard
        languages={langs}
        presets={presets.data ?? []}
        judgeEnabled={settings.data.enabled}
      />
    </div>
  );
}

function JudgeSettingsForm({
  data,
  enabledLanguageCount,
  onSaved,
}: {
  data: JudgeSettings;
  enabledLanguageCount: number;
  onSaved: () => void;
}) {
  const t = useTranslations("admin.judge");
  const update = useUpdateJudgeSettings();
  const [enabled, setEnabled] = useState(data.enabled);
  // Prefill a suggestion (the instancing proxy, or the compose default) when
  // nothing is stored yet — saved only when the admin saves.
  const suggested = data.endpoint_url === null;
  const [endpointUrl, setEndpointUrl] = useState(
    data.endpoint_url ?? data.suggested_endpoint_url,
  );
  const [concurrency, setConcurrency] = useState(String(data.max_concurrent_judgings));
  const [timeMs, setTimeMs] = useState(String(data.default_time_limit_ms));
  const [memoryMb, setMemoryMb] = useState(String(data.default_memory_limit_mb));
  const [outputKb, setOutputKb] = useState(String(data.default_output_limit_kb));

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    // Mirror the server's enable invariant for instant feedback.
    if (enabled && !endpointUrl.trim()) {
      toast(t("endpointBeforeEnabling"), { variant: "destructive" });
      return;
    }
    if (enabled && enabledLanguageCount === 0) {
      toast(t("languageBeforeEnabling"), { variant: "destructive" });
      return;
    }
    update.mutate(
      {
        enabled,
        endpoint_url: endpointUrl.trim(),
        max_concurrent_judgings: clamp(concurrency, 1, 64, 1),
        default_time_limit_ms: clamp(timeMs, 100, 60_000, 2000),
        default_memory_limit_mb: clamp(memoryMb, 16, 8192, 256),
        default_output_limit_kb: clamp(outputKb, 1, 262_144, 8192),
      },
      {
        onSuccess: () => {
          toast(t("settingsSaved"), { variant: "success" });
          onSaved();
        },
        onError: (err) =>
          toast(t("couldntSave"), {
            description: (err as Error).message,
            variant: "destructive",
          }),
      },
    );
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-5">
      <Card>
        <CardHeader>
          <CardTitle>{t("executor")}</CardTitle>
          <CardDescription>{t("executorDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="judge-enabled">{t("status")}</Label>
            <Select
              id="judge-enabled"
              value={enabled ? "on" : "off"}
              onChange={(e) => setEnabled(e.target.value === "on")}
              className="max-w-xs"
            >
              <option value="off">{t("statusOff")}</option>
              <option value="on">{t("statusOn")}</option>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="judge-endpoint">{t("endpointUrl")}</Label>
            <Input
              id="judge-endpoint"
              value={endpointUrl}
              onChange={(e) => setEndpointUrl(e.target.value)}
              placeholder="http://socket-proxy:2375"
              autoComplete="off"
            />
            <p className="text-xs text-muted-foreground">
              {suggested ? t("endpointSuggestedHint") : t("endpointHint")}
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Concurrency and default limits have sensible defaults; most installs
          never touch them, so they sit behind a disclosure. */}
      <details className="group rounded-lg border border-border bg-card">
        <summary className="cursor-pointer select-none px-6 py-4 text-sm font-medium">
          {t("advanced")}
        </summary>
        <div className="grid gap-5 border-t border-border px-6 py-5">
          <div className="grid gap-2">
            <Label htmlFor="judge-concurrency">{t("concurrency")}</Label>
            <Input
              id="judge-concurrency"
              type="number"
              min={1}
              max={64}
              value={concurrency}
              onChange={(e) => setConcurrency(e.target.value)}
              className="max-w-32"
            />
            <p className="text-xs text-muted-foreground">{t("concurrencyHint")}</p>
          </div>
          <div className="grid gap-1.5">
            <p className="text-sm font-medium">{t("defaultLimits")}</p>
            <p className="text-xs text-muted-foreground">{t("defaultLimitsDescription")}</p>
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="grid gap-2">
              <Label htmlFor="judge-time">{t("timeLimitMs")}</Label>
              <Input
                id="judge-time"
                type="number"
                min={100}
                max={60000}
                value={timeMs}
                onChange={(e) => setTimeMs(e.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="judge-memory">{t("memoryLimitMb")}</Label>
              <Input
                id="judge-memory"
                type="number"
                min={16}
                max={8192}
                value={memoryMb}
                onChange={(e) => setMemoryMb(e.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="judge-output">{t("outputLimitKb")}</Label>
              <Input
                id="judge-output"
                type="number"
                min={1}
                max={262144}
                value={outputKb}
                onChange={(e) => setOutputKb(e.target.value)}
              />
            </div>
          </div>
        </div>
      </details>

      <Button type="submit" className="w-fit" disabled={update.isPending}>
        {update.isPending ? t("saving") : t("saveChanges")}
      </Button>
    </form>
  );
}

function LanguagesCard({
  languages,
  presets,
  judgeEnabled,
}: {
  languages: JudgeLanguage[];
  presets: JudgeLanguagePreset[];
  judgeEnabled: boolean;
}) {
  const t = useTranslations("admin.judge");
  const confirm = useConfirm();
  const create = useCreateJudgeLanguage();
  const update = useUpdateJudgeLanguage();
  const remove = useDeleteJudgeLanguage();
  // null = closed; "new" = add a custom language; a language = edit it.
  const [editing, setEditing] = useState<JudgeLanguage | "new" | null>(null);

  const byKey = new Map(languages.map((l) => [l.key, l]));
  const presetKeys = new Set(presets.map((p) => p.key));
  const custom = languages.filter((l) => !presetKeys.has(l.key));
  const busy = create.isPending || update.isPending || remove.isPending;

  const onError = (err: unknown) =>
    toast(t("couldntSaveLanguage"), {
      description: (err as Error).message,
      variant: "destructive",
    });

  /** Ticking a built-in on the first time creates it from the preset; after
   *  that it's an ordinary enable/disable of the stored row (which keeps the
   *  version the operator pinned, even if a later preset moves on). */
  function togglePreset(preset: JudgeLanguagePreset, on: boolean) {
    const existing = byKey.get(preset.key);
    if (existing) {
      update.mutate({ id: existing.id, input: { enabled: on } }, { onError });
    } else if (on) {
      create.mutate({ ...preset, enabled: true }, { onError });
    }
  }

  function toggleCustom(language: JudgeLanguage, on: boolean) {
    update.mutate({ id: language.id, input: { enabled: on } }, { onError });
  }

  async function onDelete(language: JudgeLanguage) {
    const ok = await confirm({
      title: t("deleteTitle", { name: language.name }),
      description: t("deleteDescription"),
      confirmLabel: t("deleteConfirm"),
    });
    if (!ok) return;
    remove.mutate(language.id, {
      onSuccess: () => toast(t("languageDeleted"), { variant: "success" }),
      onError: (err) =>
        toast(t("couldntDelete"), {
          description: (err as Error).message,
          variant: "destructive",
        }),
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("languages")}</CardTitle>
        <CardDescription>{t("languagesDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6">
        <ul className="divide-y divide-border rounded-md border border-border">
          {presets.map((preset) => {
            const existing = byKey.get(preset.key);
            const enabled = existing?.enabled ?? false;
            const image = existing?.image_ref ?? preset.image_ref;
            const id = `lang-toggle-${preset.key}`;
            return (
              <li
                key={preset.key}
                className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
              >
                <label htmlFor={id} className="flex min-w-0 cursor-pointer items-center gap-3">
                  <input
                    id={id}
                    type="checkbox"
                    checked={enabled}
                    disabled={busy}
                    onChange={(e) => togglePreset(preset, e.target.checked)}
                    style={{ accentColor: "hsl(var(--primary))" }}
                    className="h-4 w-4 shrink-0"
                  />
                  <span className="min-w-0">
                    <span className="block font-medium">{existing?.name ?? preset.name}</span>
                    <span className="block truncate font-mono text-xs text-muted-foreground">
                      {image}
                    </span>
                  </span>
                </label>
                {existing && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setEditing(existing)}
                    aria-label={t("editNamed", { name: existing.name })}
                  >
                    {t("edit")}
                  </Button>
                )}
              </li>
            );
          })}
        </ul>

        <div className="grid gap-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="grid gap-1">
              <p className="text-sm font-medium">{t("customLanguages")}</p>
              <p className="text-xs text-muted-foreground">{t("customLanguagesDescription")}</p>
            </div>
            <Button type="button" variant="outline" size="sm" onClick={() => setEditing("new")}>
              {t("addCustomLanguage")}
            </Button>
          </div>
          {custom.length > 0 && (
            <ul className="divide-y divide-border rounded-md border border-border">
              {custom.map((language) => {
                const id = `lang-toggle-custom-${language.id}`;
                return (
                  <li
                    key={language.id}
                    className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
                  >
                    <label htmlFor={id} className="flex min-w-0 cursor-pointer items-center gap-3">
                      <input
                        id={id}
                        type="checkbox"
                        checked={language.enabled}
                        disabled={busy}
                        onChange={(e) => toggleCustom(language, e.target.checked)}
                        style={{ accentColor: "hsl(var(--primary))" }}
                        className="h-4 w-4 shrink-0"
                      />
                      <span className="min-w-0">
                        <span className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{language.name}</span>
                          <span className="font-mono text-xs text-muted-foreground">
                            {language.key}
                          </span>
                        </span>
                        <span className="block truncate font-mono text-xs text-muted-foreground">
                          {language.image_ref}
                        </span>
                      </span>
                    </label>
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setEditing(language)}
                        aria-label={t("editNamed", { name: language.name })}
                      >
                        {t("edit")}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => onDelete(language)}
                        disabled={busy}
                      >
                        {t("delete")}
                      </Button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {judgeEnabled && (
          <p className="text-xs text-muted-foreground">{t("lastLanguageHint")}</p>
        )}
      </CardContent>
      {editing !== null && (
        <LanguageDialog
          // Remount per target so the form seeds from the right language.
          key={editing === "new" ? "new" : editing.id}
          language={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </Card>
  );
}

function LanguageDialog({
  language,
  onClose,
}: {
  language: JudgeLanguage | null;
  onClose: () => void;
}) {
  const t = useTranslations("admin.judge");
  const create = useCreateJudgeLanguage();
  const update = useUpdateJudgeLanguage();
  const isEdit = language !== null;
  const [name, setName] = useState(language?.name ?? "");
  const [key, setKey] = useState(language?.key ?? "");
  const [imageRef, setImageRef] = useState(language?.image_ref ?? "");
  const [sourceFilename, setSourceFilename] = useState(language?.source_filename ?? "");
  const [compileLines, setCompileLines] = useState(argvToLines(language?.compile_command ?? null));
  const [runLines, setRunLines] = useState(argvToLines(language?.run_command ?? null));
  const [multiplier, setMultiplier] = useState(String(language?.time_multiplier ?? 1));
  const [enabled, setEnabled] = useState(language?.enabled ?? true);
  const pending = create.isPending || update.isPending;

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const compile = linesToArgv(compileLines);
    const run = linesToArgv(runLines);
    if (run.length === 0) {
      toast(t("runCommandRequired"), { variant: "destructive" });
      return;
    }
    const fields = {
      name: name.trim(),
      image_ref: imageRef.trim(),
      source_filename: sourceFilename.trim(),
      // An empty compile box means "interpreted": send null to clear it.
      compile_command: compile.length > 0 ? compile : null,
      run_command: run,
      time_multiplier: clamp(multiplier, 0.1, 20, 1),
      enabled,
    };
    const handlers = {
      onSuccess: () => {
        toast(isEdit ? t("languageSaved") : t("languageAdded"), { variant: "success" });
        onClose();
      },
      onError: (err: unknown) =>
        toast(t("couldntSaveLanguage"), {
          description: (err as Error).message,
          variant: "destructive",
        }),
    };
    if (isEdit) {
      update.mutate({ id: language.id, input: fields }, handlers);
    } else {
      create.mutate({ ...fields, key: key.trim() }, handlers);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? t("editLanguageTitle") : t("addLanguageTitle")}</DialogTitle>
          <DialogDescription>{t("languageDialogDescription")}</DialogDescription>
        </DialogHeader>
        <form className="grid gap-4" onSubmit={onSubmit}>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="lang-name">{t("languageName")}</Label>
              <Input
                id="lang-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Python 3"
                maxLength={64}
                required
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="lang-key">{t("languageKey")}</Label>
              <Input
                id="lang-key"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="python3"
                pattern="[a-z0-9][a-z0-9_\-]{0,31}"
                disabled={isEdit}
                required={!isEdit}
                className="font-mono"
              />
            </div>
          </div>
          <p className="-mt-2 text-xs text-muted-foreground">{t("languageKeyHint")}</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="lang-image">{t("imageRef")}</Label>
              <Input
                id="lang-image"
                value={imageRef}
                onChange={(e) => setImageRef(e.target.value)}
                placeholder="python:3.13-slim"
                maxLength={256}
                required
                className="font-mono"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="lang-filename">{t("sourceFilename")}</Label>
              <Input
                id="lang-filename"
                value={sourceFilename}
                onChange={(e) => setSourceFilename(e.target.value)}
                placeholder="solution.py"
                required
                className="font-mono"
              />
            </div>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="lang-compile">{t("compileCommand")}</Label>
            <textarea
              id="lang-compile"
              className={TEXTAREA_CLASS}
              value={compileLines}
              onChange={(e) => setCompileLines(e.target.value)}
              placeholder={"g++\n-O2\n-o\n{work}/main\n{source}"}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="lang-run">{t("runCommand")}</Label>
            <textarea
              id="lang-run"
              className={TEXTAREA_CLASS}
              value={runLines}
              onChange={(e) => setRunLines(e.target.value)}
              placeholder={"python3\n{source}"}
              required
            />
            <p className="text-xs text-muted-foreground">
              {t.rich("commandHint", {
                mono: (chunks) => <span className="font-mono">{chunks}</span>,
              })}
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="lang-multiplier">{t("timeMultiplier")}</Label>
              <Input
                id="lang-multiplier"
                type="number"
                step="0.1"
                min={0.1}
                max={20}
                value={multiplier}
                onChange={(e) => setMultiplier(e.target.value)}
                className="max-w-32"
              />
              <p className="text-xs text-muted-foreground">{t("timeMultiplierHint")}</p>
            </div>
            <label className="flex items-center gap-2 self-start pt-7 text-sm">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                style={{ accentColor: "hsl(var(--primary))" }}
              />
              {t("languageEnabled")}
            </label>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={pending}>
              {pending ? t("saving") : isEdit ? t("saveChanges") : t("addLanguage")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
