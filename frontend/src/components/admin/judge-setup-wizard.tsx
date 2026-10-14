"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useApplyJudgeSetup,
  useCheckJudgeConnection,
  useUpdateJudgeSettings,
} from "@/lib/hooks/use-judge";
import type {
  JudgeCheckResult,
  JudgeLanguage,
  JudgeLanguagePreset,
  JudgeSettings,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { toast } from "@/stores/toast";

// The code judge's guided setup (#446/#447), in the style of the first-run
// /setup wizard: Connect → Languages → Review & enable. The infrastructure step
// is one overlay command (docker-compose.judge.yml), after which the endpoint is
// detected; the rest is ticking languages. Everything is applied by one atomic
// backend call at the end, so an abandoned or failed setup leaves nothing
// half-configured.

export const OVERLAY_COMMAND =
  "docker compose -f docker-compose.yml -f docker-compose.judge.yml up -d";

/** Pre-ticked on a first setup: one interpreted, two compiled — covers most
 *  events out of the box. */
const DEFAULT_PRESETS = ["python3", "cpp", "java"];

export function JudgeSetupWizard({
  settings,
  presets,
  languages,
  onDone,
  onCancel,
}: {
  settings: JudgeSettings;
  presets: JudgeLanguagePreset[];
  languages: JudgeLanguage[];
  onDone: () => void;
  /** Present when re-running setup on an already-on judge. */
  onCancel?: () => void;
}) {
  const t = useTranslations("admin.judge.setup");
  const [step, setStep] = useState(0);

  // Step 1 — connect.
  const [endpoint, setEndpoint] = useState(
    settings.endpoint_url ?? settings.suggested_endpoint_url,
  );
  const [check, setCheck] = useState<JudgeCheckResult | null>(null);
  const saveEndpoint = useUpdateJudgeSettings();
  const runCheck = useCheckJudgeConnection();

  // Step 2 — languages. A re-run starts from what's enabled now.
  const enabledPresetKeys = presets
    .map((p) => p.key)
    .filter((key) => languages.some((l) => l.key === key && l.enabled));
  const [selected, setSelected] = useState<string[]>(
    enabledPresetKeys.length > 0 ? enabledPresetKeys : DEFAULT_PRESETS,
  );

  const apply = useApplyJudgeSetup();
  const steps = [t("stepConnect"), t("stepLanguages"), t("stepReview")];
  const checking = saveEndpoint.isPending || runCheck.isPending;

  function doCheck() {
    setCheck(null);
    const probe = () =>
      runCheck.mutate(undefined, {
        onSuccess: setCheck,
        onError: (err) =>
          toast(t("checkFailed"), { description: (err as Error).message, variant: "destructive" }),
      });
    // The check only ever probes the *saved* endpoint, so save a typed one first.
    const typed = endpoint.trim();
    if (!settings.endpoint_managed && typed !== (settings.endpoint_url ?? "")) {
      saveEndpoint.mutate(
        { endpoint_url: typed },
        {
          onSuccess: probe,
          onError: (err) =>
            toast(t("checkFailed"), { description: (err as Error).message, variant: "destructive" }),
        },
      );
    } else {
      probe();
    }
  }

  function toggle(key: string, on: boolean) {
    setSelected((cur) => (on ? [...cur, key] : cur.filter((k) => k !== key)));
  }

  function finish() {
    // Keep catalog order, whatever order things were ticked in.
    const keys = presets.map((p) => p.key).filter((k) => selected.includes(k));
    apply.mutate(keys, {
      onSuccess: () => {
        toast(t("enabledToast"), { variant: "success" });
        onDone();
      },
      onError: (err) =>
        toast(t("enableFailed"), { description: (err as Error).message, variant: "destructive" }),
    });
  }

  const legLabel = (name: string) =>
    name === "endpoint_reachable"
      ? t("legReachable")
      : name === "proxy_restricted"
        ? t("legRestricted")
        : name;

  const chosen = presets.filter((p) => selected.includes(p.key));

  return (
    <div className="grid max-w-2xl gap-5">
      <div className="flex flex-wrap items-center gap-2" aria-hidden>
        {steps.map((name, i) => (
          <div key={name} className="flex items-center gap-2">
            <span
              className={cn(
                "flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold",
                i <= step ? "bg-primary text-primary-foreground" : "bg-secondary text-secondary-foreground",
              )}
            >
              {i + 1}
            </span>
            <span className={cn("text-xs", i === step ? "font-medium text-foreground" : "text-muted-foreground")}>
              {name}
            </span>
            {i < steps.length - 1 && <span className="mx-1 h-px w-6 bg-border" />}
          </div>
        ))}
      </div>

      <Card>
        {step === 0 && (
          <>
            <CardHeader>
              <CardTitle>{t("connectTitle")}</CardTitle>
              <CardDescription>{t("connectDescription")}</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4">
              {settings.endpoint_managed ? (
                <div className="rounded-md border border-success/45 bg-success/10 px-4 py-3 text-sm">
                  <p className="font-medium">{t("detectedTitle")}</p>
                  <p className="mt-1 font-mono text-xs text-muted-foreground">{settings.endpoint_url}</p>
                </div>
              ) : (
                <>
                  <div className="grid gap-2">
                    <p className="text-sm">{t("overlayInstruction")}</p>
                    <div className="flex items-start gap-2">
                      <code className="block flex-1 overflow-x-auto rounded-md border border-border bg-muted px-3 py-2 font-mono text-xs">
                        {OVERLAY_COMMAND}
                      </code>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          void navigator.clipboard?.writeText(OVERLAY_COMMAND);
                          toast(t("copied"), { variant: "success" });
                        }}
                      >
                        {t("copy")}
                      </Button>
                    </div>
                    <p className="text-xs text-muted-foreground">{t("overlayHint")}</p>
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="judge-setup-endpoint">{t("endpointLabel")}</Label>
                    <Input
                      id="judge-setup-endpoint"
                      value={endpoint}
                      onChange={(e) => {
                        setEndpoint(e.target.value);
                        setCheck(null);
                      }}
                      className="font-mono"
                      autoComplete="off"
                    />
                    <p className="text-xs text-muted-foreground">{t("endpointHint")}</p>
                  </div>
                </>
              )}

              <div>
                <Button type="button" onClick={doCheck} disabled={checking || !endpoint.trim()}>
                  {checking ? t("checking") : t("checkConnection")}
                </Button>
              </div>

              {check && (
                <ul className="grid gap-2" aria-label={t("checkResults")}>
                  {check.legs.map((leg) => (
                    <li
                      key={leg.name}
                      className={cn(
                        "rounded-md border px-3 py-2 text-sm",
                        leg.ok ? "border-success/45 bg-success/10" : "border-destructive/45 bg-destructive/10",
                      )}
                    >
                      <span className="font-medium">
                        {leg.ok ? "✓" : "✗"} {legLabel(leg.name)}
                      </span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">{leg.detail}</span>
                    </li>
                  ))}
                  {!check.ok && (
                    <li className="text-xs text-muted-foreground">{t("checkFixHint")}</li>
                  )}
                </ul>
              )}
            </CardContent>
          </>
        )}

        {step === 1 && (
          <>
            <CardHeader>
              <CardTitle>{t("languagesTitle")}</CardTitle>
              <CardDescription>{t("languagesDescription")}</CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="divide-y divide-border rounded-md border border-border">
                {presets.map((preset) => {
                  const id = `judge-setup-lang-${preset.key}`;
                  const pinned = languages.find((l) => l.key === preset.key)?.image_ref;
                  return (
                    <li key={preset.key} className="px-4 py-3">
                      <label htmlFor={id} className="flex cursor-pointer items-center gap-3">
                        <input
                          id={id}
                          type="checkbox"
                          checked={selected.includes(preset.key)}
                          onChange={(e) => toggle(preset.key, e.target.checked)}
                          style={{ accentColor: "hsl(var(--primary))" }}
                          className="h-4 w-4 shrink-0"
                        />
                        <span className="min-w-0">
                          <span className="block font-medium">{preset.name}</span>
                          <span className="block truncate font-mono text-xs text-muted-foreground">
                            {pinned ?? preset.image_ref}
                          </span>
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
              <p className="mt-3 text-xs text-muted-foreground">{t("languagesHint")}</p>
            </CardContent>
          </>
        )}

        {step === 2 && (
          <>
            <CardHeader>
              <CardTitle>{t("reviewTitle")}</CardTitle>
              <CardDescription>{t("reviewDescription")}</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 text-sm">
              <div className="grid gap-1">
                <span className="text-xs text-muted-foreground">{t("reviewEndpoint")}</span>
                <span className="font-mono text-xs">{settings.endpoint_managed ? settings.endpoint_url : endpoint.trim()}</span>
              </div>
              <div className="grid gap-1">
                <span className="text-xs text-muted-foreground">{t("reviewLanguages")}</span>
                <span>{chosen.map((p) => p.name).join(", ")}</span>
              </div>
              <p className="text-xs text-muted-foreground">{t("reviewNextSteps")}</p>
            </CardContent>
          </>
        )}

        <CardContent className="flex items-center justify-between border-t border-border pt-4">
          {step === 0 && onCancel ? (
            <Button type="button" variant="ghost" onClick={onCancel}>
              {t("cancel")}
            </Button>
          ) : (
            <Button
              type="button"
              variant="ghost"
              onClick={() => setStep((s) => s - 1)}
              disabled={step === 0}
            >
              {t("back")}
            </Button>
          )}
          {step === 0 && (
            <Button type="button" onClick={() => setStep(1)} disabled={!check?.ok}>
              {t("next")}
            </Button>
          )}
          {step === 1 && (
            <Button type="button" onClick={() => setStep(2)} disabled={selected.length === 0}>
              {t("next")}
            </Button>
          )}
          {step === 2 && (
            <Button type="button" onClick={finish} disabled={apply.isPending}>
              {apply.isPending ? t("enabling") : t("enable")}
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
