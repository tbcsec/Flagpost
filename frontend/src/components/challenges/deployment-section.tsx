"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useChallengeDeployment,
  useDeleteChallengeDeployment,
  useUpsertChallengeDeployment,
} from "@/lib/hooks/use-instances";
import type { ChallengeDeployment, ChallengeDeploymentUpdate } from "@/lib/types";
import { useConfirm } from "@/components/ui/confirm";
import { toast } from "@/stores/toast";

// Challenge editor → Deployment (#266, ADR-0036). The per-challenge spec that
// turns a jeopardy challenge into an instanced one: a Docker image, the TCP
// ports competitors reach, environment, guardrails, lifetime, and the flag mode
// (a shared flag, or a unique per-instance flag rendered from a template). At
// most one per challenge — the editor upserts it in place. Nothing here launches
// an instance; that's the competitor surface.

// The placeholder a unique flag_template must contain — the backend substitutes
// a fresh random token for it per instance (must match the backend constant).
const FLAG_TEMPLATE_TOKEN = "<random>";

function clampNum(value: string, lo: number, hi: number, fallback: number): number {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(hi, Math.max(lo, n));
}

export function DeploymentSection({
  competitionId,
  challengeId,
}: {
  competitionId: string;
  challengeId: string;
}) {
  const t = useTranslations("challenges.admin.deployment");
  const { data, isLoading } = useChallengeDeployment(competitionId, challengeId);

  return (
    <div className="grid gap-3">
      <div>
        <Label>{t("title")}</Label>
        <p className="text-xs text-muted-foreground">{t("description")}</p>
      </div>
      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <DeploymentForm
          key={data?.id ?? "new"}
          competitionId={competitionId}
          challengeId={challengeId}
          data={data ?? null}
        />
      )}
    </div>
  );
}

function DeploymentForm({
  competitionId,
  challengeId,
  data,
}: {
  competitionId: string;
  challengeId: string;
  data: ChallengeDeployment | null;
}) {
  const t = useTranslations("challenges.admin.deployment");
  const upsert = useUpsertChallengeDeployment(competitionId, challengeId);
  const remove = useDeleteChallengeDeployment(competitionId, challengeId);
  const confirm = useConfirm();

  const [imageRef, setImageRef] = useState(data?.image_ref ?? "");
  const [exposure, setExposure] = useState(data?.exposure ?? "tcp");
  const [ports, setPorts] = useState<number[]>(data?.ports ?? []);
  const [env, setEnv] = useState<[string, string][]>(
    Object.entries(data?.env ?? {}),
  );
  const [lifetime, setLifetime] = useState(
    data?.lifetime_s != null ? String(data.lifetime_s) : "",
  );
  const [cap, setCap] = useState(String(data?.per_subject_cap ?? 1));
  const limits = (data?.resource_limits ?? {}) as Record<string, unknown>;
  const [cpu, setCpu] = useState(limits.cpu != null ? String(limits.cpu) : "");
  const [memoryMb, setMemoryMb] = useState(
    limits.memory_mb != null ? String(limits.memory_mb) : "",
  );
  const [pids, setPids] = useState(
    limits.pids != null ? String(limits.pids) : "",
  );
  const [flagMode, setFlagMode] = useState(data?.flag_mode ?? "static");
  const [flagTemplate, setFlagTemplate] = useState(data?.flag_template ?? "");

  function onSave() {
    if (!imageRef.trim()) {
      toast(t("imageRequired"), { variant: "destructive" });
      return;
    }
    if (exposure === "tcp" && ports.length === 0) {
      toast(t("portsRequired"), { variant: "destructive" });
      return;
    }
    // A unique flag needs a template with the <random> placeholder so every
    // instance renders a distinct flag; the backend re-validates this.
    if (flagMode === "unique_per_instance" && !flagTemplate.includes(FLAG_TEMPLATE_TOKEN)) {
      toast(t("flagTemplateRequired", { token: FLAG_TEMPLATE_TOKEN }), {
        variant: "destructive",
      });
      return;
    }
    const resourceLimits: Record<string, number> = {};
    if (cpu) resourceLimits.cpu = clampNum(cpu, 0.1, 64, 1);
    if (memoryMb) resourceLimits.memory_mb = clampNum(memoryMb, 16, 131072, 256);
    if (pids) resourceLimits.pids = clampNum(pids, 16, 65536, 256);

    const payload: ChallengeDeploymentUpdate = {
      backend: "docker",
      image_ref: imageRef.trim(),
      exposure,
      // TCP and HTTP both carry the container port(s); HTTP uses the first as the
      // ingress upstream (defaulting to 80 when omitted). "none" carries none.
      ports: exposure === "none" ? [] : ports,
      env: Object.fromEntries(
        env.filter(([k]) => k.trim()).map(([k, v]) => [k.trim(), v]),
      ),
      resource_limits: Object.keys(resourceLimits).length ? resourceLimits : null,
      lifetime_s: lifetime ? clampNum(lifetime, 60, 86400, 3600) : null,
      per_subject_cap: clampNum(cap, 1, 100, 1),
      flag_mode: flagMode,
      flag_template:
        flagMode === "unique_per_instance" ? flagTemplate.trim() : null,
    };
    upsert.mutate(payload, {
      onSuccess: () => toast(t("saved"), { variant: "success" }),
      onError: (err) =>
        toast(t("couldntSave"), {
          description: (err as Error).message,
          variant: "destructive",
        }),
    });
  }

  async function onRemove() {
    if (
      await confirm({
        title: t("removeConfirmTitle"),
        description: t("removeConfirmDescription"),
        confirmLabel: t("removeConfirmLabel"),
      })
    ) {
      remove.mutate(undefined, {
        onSuccess: () => toast(t("removed"), { variant: "success" }),
        onError: (err) =>
          toast(t("couldntRemove"), {
            description: (err as Error).message,
            variant: "destructive",
          }),
      });
    }
  }

  return (
    <div className="grid gap-4 rounded-md border border-border p-4">
      <div className="grid gap-2">
        <Label htmlFor={`dep-image-${challengeId}`}>{t("imageRef")}</Label>
        <Input
          id={`dep-image-${challengeId}`}
          value={imageRef}
          onChange={(e) => setImageRef(e.target.value)}
          placeholder="ghcr.io/you/chal:latest"
          autoComplete="off"
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="grid gap-2">
          <Label htmlFor={`dep-exposure-${challengeId}`}>{t("exposure")}</Label>
          <Select
            id={`dep-exposure-${challengeId}`}
            value={exposure}
            onChange={(e) => setExposure(e.target.value)}
          >
            <option value="tcp">{t("exposureTcp")}</option>
            <option value="http">{t("exposureHttp")}</option>
            <option value="none">{t("exposureNone")}</option>
          </Select>
        </div>
        <div className="grid gap-2">
          <Label htmlFor={`dep-cap-${challengeId}`}>{t("perSubjectCap")}</Label>
          <Input
            id={`dep-cap-${challengeId}`}
            type="number"
            min={1}
            max={100}
            value={cap}
            onChange={(e) => setCap(e.target.value)}
          />
        </div>
      </div>

      {exposure !== "none" && (
        <PortsEditor value={ports} onChange={setPorts} http={exposure === "http"} />
      )}

      <EnvEditor value={env} onChange={setEnv} />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="grid gap-2">
          <Label htmlFor={`dep-cpu-${challengeId}`}>{t("cpu")}</Label>
          <Input
            id={`dep-cpu-${challengeId}`}
            type="number"
            min={0.1}
            max={64}
            step={0.1}
            value={cpu}
            onChange={(e) => setCpu(e.target.value)}
            placeholder={t("siteDefault")}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor={`dep-mem-${challengeId}`}>{t("memory")}</Label>
          <Input
            id={`dep-mem-${challengeId}`}
            type="number"
            min={16}
            max={131072}
            value={memoryMb}
            onChange={(e) => setMemoryMb(e.target.value)}
            placeholder={t("siteDefault")}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor={`dep-pids-${challengeId}`}>{t("pids")}</Label>
          <Input
            id={`dep-pids-${challengeId}`}
            type="number"
            min={16}
            max={65536}
            value={pids}
            onChange={(e) => setPids(e.target.value)}
            placeholder={t("siteDefault")}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor={`dep-lifetime-${challengeId}`}>{t("lifetime")}</Label>
          <Input
            id={`dep-lifetime-${challengeId}`}
            type="number"
            min={60}
            max={86400}
            value={lifetime}
            onChange={(e) => setLifetime(e.target.value)}
            placeholder={t("competitionDefault")}
          />
        </div>
      </div>

      <div className="grid gap-3 border-t border-border pt-4">
        <div className="grid gap-2">
          <Label htmlFor={`dep-flagmode-${challengeId}`}>{t("flagMode")}</Label>
          <Select
            id={`dep-flagmode-${challengeId}`}
            value={flagMode}
            onChange={(e) => setFlagMode(e.target.value)}
          >
            <option value="static">{t("flagModeStatic")}</option>
            <option value="unique_per_instance">{t("flagModeUnique")}</option>
          </Select>
          <p className="text-xs text-muted-foreground">
            {flagMode === "unique_per_instance"
              ? t("flagModeUniqueHelp")
              : t("flagModeStaticHelp")}
          </p>
        </div>
        {flagMode === "unique_per_instance" && (
          <div className="grid gap-2">
            <Label htmlFor={`dep-flagtemplate-${challengeId}`}>
              {t("flagTemplate")}
            </Label>
            <Input
              id={`dep-flagtemplate-${challengeId}`}
              value={flagTemplate}
              onChange={(e) => setFlagTemplate(e.target.value)}
              placeholder="flag{pwned-<random>}"
              autoComplete="off"
              spellCheck={false}
            />
            <p className="text-xs text-muted-foreground">
              {t("flagTemplateHelp", { token: FLAG_TEMPLATE_TOKEN })}
            </p>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" onClick={onSave} disabled={upsert.isPending}>
          {upsert.isPending
            ? t("saving")
            : data
              ? t("update")
              : t("create")}
        </Button>
        {data && (
          <Button
            type="button"
            variant="ghost"
            className="text-destructive"
            onClick={onRemove}
            disabled={remove.isPending}
          >
            {t("remove")}
          </Button>
        )}
      </div>
    </div>
  );
}

/** A chip editor for the container ports a challenge exposes. */
function PortsEditor({
  value,
  onChange,
  http = false,
}: {
  value: number[];
  onChange: (ports: number[]) => void;
  http?: boolean;
}) {
  const t = useTranslations("challenges.admin.deployment");
  const [draft, setDraft] = useState("");

  function add() {
    const n = Number(draft);
    if (Number.isInteger(n) && n > 0 && n < 65536 && !value.includes(n)) {
      onChange([...value, n]);
    }
    setDraft("");
  }

  return (
    <div className="grid gap-2">
      <Label>{t("ports")}</Label>
      {http && (
        <p className="text-xs text-muted-foreground">{t("portsHttpHint")}</p>
      )}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {value.map((p) => (
            <span
              key={p}
              className="inline-flex items-center gap-1 rounded-full border border-border px-2.5 py-0.5 text-xs"
            >
              {p}
              <button
                type="button"
                onClick={() => onChange(value.filter((x) => x !== p))}
                className="text-muted-foreground hover:text-destructive"
                aria-label={t("removePortAria", { port: p })}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <Input
          type="number"
          min={1}
          max={65535}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={t("portPlaceholder")}
          className="max-w-40"
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <Button type="button" variant="outline" onClick={add} disabled={!draft.trim()}>
          {t("addPort")}
        </Button>
      </div>
    </div>
  );
}

/** A key/value editor for the instance's environment. */
function EnvEditor({
  value,
  onChange,
}: {
  value: [string, string][];
  onChange: (env: [string, string][]) => void;
}) {
  const t = useTranslations("challenges.admin.deployment");

  function set(i: number, side: 0 | 1, v: string) {
    const next = value.map((row, idx) =>
      idx === i ? ((side === 0 ? [v, row[1]] : [row[0], v]) as [string, string]) : row,
    );
    onChange(next);
  }

  return (
    <div className="grid gap-2">
      <Label>{t("env")}</Label>
      {value.map((row, i) => (
        <div key={i} className="flex gap-2">
          <Input
            value={row[0]}
            onChange={(e) => set(i, 0, e.target.value)}
            placeholder={t("envKey")}
            autoComplete="off"
            className="font-mono"
          />
          <Input
            value={row[1]}
            onChange={(e) => set(i, 1, e.target.value)}
            placeholder={t("envValue")}
            autoComplete="off"
            className="font-mono"
          />
          <button
            type="button"
            onClick={() => onChange(value.filter((_, idx) => idx !== i))}
            className="px-2 text-muted-foreground hover:text-destructive"
            aria-label={t("removeEnvAria")}
          >
            ×
          </button>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        className="w-fit"
        onClick={() => onChange([...value, ["", ""]])}
      >
        {t("addEnv")}
      </Button>
    </div>
  );
}
