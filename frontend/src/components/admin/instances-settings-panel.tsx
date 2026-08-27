"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useInstanceSettings,
  useTestInstanceConnection,
  useUpdateInstanceSettings,
} from "@/lib/hooks/use-instances";
import type {
  InstanceConnectionLeg,
  InstanceConnectionResult,
  InstanceSettings,
  InstanceSettingsUpdate,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { toast } from "@/stores/toast";

// Admin → Site settings → Instances (#266, ADR-0036). The site-wide provisioner
// config: a container-runtime endpoint (always a least-privilege socket proxy),
// the public host competitors connect to, the TCP port range, default resource
// limits, and the global concurrency ceiling. The registry credential is
// write-only exactly like the SMTP password / AI key. "Test connection" runs the
// provisioner's staged validate() and shows each leg, so a misconfiguration
// surfaces as a labelled error before event day, not as a dead connection string.
function clamp(value: string, lo: number, hi: number, fallback: number): number {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(hi, Math.max(lo, n));
}

export function InstancesSettingsPanel() {
  const { data, isLoading } = useInstanceSettings();
  // No updated_at on the settings row, so reseed the form after each save with a
  // nonce (clears the write-only credential field + shows canonical server
  // values) rather than the AI panel's key-on-timestamp remount.
  const [nonce, setNonce] = useState(0);
  if (isLoading || !data) return <Skeleton className="h-64 w-full" />;
  return (
    <InstancesSettingsForm
      key={nonce}
      data={data}
      onSaved={() => setNonce((n) => n + 1)}
    />
  );
}

function InstancesSettingsForm({
  data,
  onSaved,
}: {
  data: InstanceSettings;
  onSaved: () => void;
}) {
  const t = useTranslations("admin.instances");
  const update = useUpdateInstanceSettings();
  const test = useTestInstanceConnection();

  const [enabled, setEnabled] = useState(data.enabled);
  const [backend, setBackend] = useState(data.backend || "docker");
  const [endpointUrl, setEndpointUrl] = useState(data.endpoint_url ?? "");
  const [publicHost, setPublicHost] = useState(data.public_host ?? "");
  const [credential, setCredential] = useState("");
  const [clearCredential, setClearCredential] = useState(false);
  const [portMin, setPortMin] = useState(String(data.tcp_port_min));
  const [portMax, setPortMax] = useState(String(data.tcp_port_max));
  const [cpu, setCpu] = useState(String(data.default_cpu));
  const [memoryMb, setMemoryMb] = useState(String(data.default_memory_mb));
  const [pids, setPids] = useState(String(data.default_pids));
  const [maxConcurrent, setMaxConcurrent] = useState(String(data.max_concurrent));
  const [egress, setEgress] = useState(data.egress_policy || "deny");
  const [result, setResult] = useState<InstanceConnectionResult | null>(null);

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    // Mirror the server invariants for instant feedback.
    if (enabled && (!endpointUrl.trim() || !publicHost.trim())) {
      toast(t("setBeforeEnabling"), { variant: "destructive" });
      return;
    }
    const min = clamp(portMin, 1, 65535, 30000);
    const max = clamp(portMax, 1, 65535, 32767);
    if (min > max) {
      toast(t("portRangeInvalid"), { variant: "destructive" });
      return;
    }
    const payload: InstanceSettingsUpdate = {
      enabled,
      backend,
      endpoint_url: endpointUrl.trim() || null,
      public_host: publicHost.trim() || null,
      tcp_port_min: min,
      tcp_port_max: max,
      default_cpu: clamp(cpu, 0.1, 64, 1),
      default_memory_mb: clamp(memoryMb, 16, 131072, 256),
      default_pids: clamp(pids, 16, 65536, 256),
      max_concurrent: clamp(maxConcurrent, 1, 100000, 100),
      egress_policy: egress,
      // Only touch the credential when the admin typed a new one or asked to clear it.
      ...(clearCredential
        ? { registry_credentials: "" }
        : credential
          ? { registry_credentials: credential }
          : {}),
    };
    update.mutate(payload, {
      onSuccess: () => {
        toast(t("settingsSaved"), { variant: "success" });
        onSaved();
      },
      onError: (err) =>
        toast(t("couldntSave"), {
          description: (err as Error).message,
          variant: "destructive",
        }),
    });
  }

  function onTest() {
    setResult(null);
    test.mutate(undefined, {
      onSuccess: (r) => setResult(r),
      onError: (err) =>
        toast(t("couldntTest"), {
          description: (err as Error).message,
          variant: "destructive",
        }),
    });
  }

  const credentialPlaceholder = clearCredential
    ? t("credentialWillClear")
    : data.registry_credentials_set
      ? t("credentialUnchanged")
      : t("credentialNotSet");

  const testReady = Boolean(data.endpoint_url && data.public_host);

  return (
    <form onSubmit={onSubmit} className="grid max-w-2xl gap-5">
      <Card>
        <CardHeader>
          <CardTitle>{t("provider")}</CardTitle>
          <CardDescription>{t("providerDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="inst-enabled">{t("status")}</Label>
            <Select
              id="inst-enabled"
              value={enabled ? "on" : "off"}
              onChange={(e) => setEnabled(e.target.value === "on")}
              className="max-w-xs"
            >
              <option value="off">{t("statusOff")}</option>
              <option value="on">{t("statusOn")}</option>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="inst-backend">{t("backend")}</Label>
            <Select
              id="inst-backend"
              value={backend}
              onChange={(e) => setBackend(e.target.value)}
              className="max-w-xs"
            >
              <option value="docker">{t("backendDocker")}</option>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="inst-endpoint">{t("endpointUrl")}</Label>
            <Input
              id="inst-endpoint"
              value={endpointUrl}
              onChange={(e) => setEndpointUrl(e.target.value)}
              placeholder="http://socket-proxy:2375"
              autoComplete="off"
            />
            <p className="text-xs text-muted-foreground">{t("endpointHint")}</p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="inst-public-host">{t("publicHost")}</Label>
            <Input
              id="inst-public-host"
              value={publicHost}
              onChange={(e) => setPublicHost(e.target.value)}
              placeholder="chal.example.org"
              autoComplete="off"
            />
            <p className="text-xs text-muted-foreground">{t("publicHostHint")}</p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="inst-credential">{t("registryCredential")}</Label>
            <Input
              id="inst-credential"
              type="password"
              value={credential}
              onChange={(e) => {
                setCredential(e.target.value);
                if (e.target.value) setClearCredential(false);
              }}
              disabled={clearCredential}
              autoComplete="new-password"
              placeholder={credentialPlaceholder}
            />
            <p className="text-xs text-muted-foreground">
              {t("registryCredentialHint")}
            </p>
            {data.registry_credentials_set && (
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={clearCredential}
                  onChange={(e) => {
                    setClearCredential(e.target.checked);
                    if (e.target.checked) setCredential("");
                  }}
                />
                {t("removeStoredCredential")}
              </label>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("exposure")}</CardTitle>
          <CardDescription>{t("exposureDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-3">
          <div className="grid gap-2">
            <Label htmlFor="inst-port-min">{t("portMin")}</Label>
            <Input
              id="inst-port-min"
              type="number"
              min={1}
              max={65535}
              value={portMin}
              onChange={(e) => setPortMin(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="inst-port-max">{t("portMax")}</Label>
            <Input
              id="inst-port-max"
              type="number"
              min={1}
              max={65535}
              value={portMax}
              onChange={(e) => setPortMax(e.target.value)}
            />
          </div>
          <div className="col-span-2 grid gap-2">
            <Label htmlFor="inst-egress">{t("egressPolicy")}</Label>
            <Select
              id="inst-egress"
              value={egress}
              onChange={(e) => setEgress(e.target.value)}
              className="max-w-xs"
            >
              <option value="deny">{t("egressDeny")}</option>
              <option value="allow">{t("egressAllow")}</option>
            </Select>
            <p className="text-xs text-muted-foreground">{t("egressHint")}</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("limits")}</CardTitle>
          <CardDescription>{t("limitsDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-3">
          <div className="grid gap-2">
            <Label htmlFor="inst-cpu">{t("defaultCpu")}</Label>
            <Input
              id="inst-cpu"
              type="number"
              min={0.1}
              max={64}
              step={0.1}
              value={cpu}
              onChange={(e) => setCpu(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="inst-memory">{t("defaultMemory")}</Label>
            <Input
              id="inst-memory"
              type="number"
              min={16}
              max={131072}
              value={memoryMb}
              onChange={(e) => setMemoryMb(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="inst-pids">{t("defaultPids")}</Label>
            <Input
              id="inst-pids"
              type="number"
              min={16}
              max={65536}
              value={pids}
              onChange={(e) => setPids(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="inst-max-concurrent">{t("maxConcurrent")}</Label>
            <Input
              id="inst-max-concurrent"
              type="number"
              min={1}
              max={100000}
              value={maxConcurrent}
              onChange={(e) => setMaxConcurrent(e.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" className="w-fit" disabled={update.isPending}>
          {update.isPending ? t("saving") : t("saveChanges")}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={onTest}
          disabled={test.isPending || !testReady}
          title={testReady ? t("testProbe") : t("testSaveFirst")}
        >
          {test.isPending ? t("testing") : t("testConnection")}
        </Button>
      </div>

      {result && <TestResult result={result} />}
    </form>
  );
}

/** The staged validate() run — each leg (reachable, privilege posture, network
 *  isolation, image pull, public reachability) reported on its own so a field
 *  misconfiguration reads as a labelled, actionable error. */
function TestResult({ result }: { result: InstanceConnectionResult }) {
  const t = useTranslations("admin.instances");
  return (
    <Card className="max-w-2xl">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          {t("connectionTest")}
          <Badge variant={result.ok ? "success" : "destructive"}>
            {result.ok ? t("resultPass") : t("resultFail")}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        {result.legs.map((leg, i) => (
          <TestLeg key={`${leg.name}-${i}`} leg={leg} />
        ))}
      </CardContent>
    </Card>
  );
}

function TestLeg({ leg }: { leg: InstanceConnectionLeg }) {
  const t = useTranslations("admin.instances");
  return (
    <div className="grid gap-1">
      <div className="flex items-center gap-2">
        <Badge variant={leg.ok ? "success" : "destructive"}>
          {leg.ok ? t("legOk") : t("legFailed")}
        </Badge>
        <span className="font-mono text-sm font-medium">{leg.name}</span>
      </div>
      <p
        className={cn(
          "text-xs",
          leg.ok ? "text-muted-foreground" : "text-destructive",
        )}
      >
        {leg.detail}
      </p>
    </div>
  );
}
