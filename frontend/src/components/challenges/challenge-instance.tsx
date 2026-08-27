"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { formatCountdown, useCountdown } from "@/lib/hooks/use-countdown";
import {
  useDestroyInstance,
  useExtendInstance,
  useLaunchInstance,
  useMyInstance,
} from "@/lib/hooks/use-instances";
import { useEnabledModules } from "@/lib/hooks/use-modules";
import type { Instance, InstanceEndpoint } from "@/lib/types";
import { toast } from "@/stores/toast";

// Challenge detail → Instance (#266, ADR-0036). A competitor's own isolated,
// running copy of the challenge: launch it, watch it come up live over the
// activity room, copy its connection details, extend it before it expires, and
// stop it. Only rendered when the challenge is instanced AND the instances
// module is enabled for the competition; the launch route enforces the rest
// (competition running, caps, demo mode) and its errors surface as toasts.

function endpointText(ep: InstanceEndpoint): string {
  if (ep.kind === "http" && ep.url) return ep.url;
  if (ep.kind === "tcp" && ep.host && ep.port) return `nc ${ep.host} ${ep.port}`;
  return [ep.host, ep.port].filter(Boolean).join(":");
}

const ACTIVE_PENDING = new Set(["requested", "provisioning"]);

export function ChallengeInstance({
  competitionId,
  challengeId,
  instanced,
}: {
  competitionId: string;
  challengeId: string;
  instanced: boolean;
}) {
  const t = useTranslations("challenges.instance");
  const { data: enabledModules } = useEnabledModules(competitionId, instanced);
  const moduleOn = enabledModules?.includes("instances") ?? false;
  const active = instanced && moduleOn;

  const {
    data: instance,
    isLoading,
    isError,
    refetch,
  } = useMyInstance(competitionId, challengeId, active);
  const launch = useLaunchInstance(competitionId, challengeId);
  const extend = useExtendInstance(competitionId, challengeId);
  const destroy = useDestroyInstance(competitionId, challengeId);
  const confirm = useConfirm();

  // Stable so the countdown-crossed-zero effect fires once per crossing rather
  // than on every re-render (`refetch` is stable across renders).
  const handleExpired = useCallback(() => {
    void refetch();
  }, [refetch]);

  if (!active) return null;

  function onLaunch() {
    launch.mutate(undefined, {
      onError: (err) =>
        toast(t("launchError"), {
          description: (err as Error).message,
          variant: "destructive",
        }),
    });
  }

  function onExtend() {
    extend.mutate(undefined, {
      onSuccess: () => toast(t("extended"), { variant: "success" }),
      onError: (err) =>
        toast(t("extendError"), {
          description: (err as Error).message,
          variant: "destructive",
        }),
    });
  }

  async function onDestroy() {
    if (
      await confirm({
        title: t("destroyConfirmTitle"),
        description: t("destroyConfirmDescription"),
        confirmLabel: t("destroy"),
      })
    ) {
      destroy.mutate(undefined, {
        onError: (err) =>
          toast(t("destroyError"), {
            description: (err as Error).message,
            variant: "destructive",
          }),
      });
    }
  }

  return (
    <div className="grid gap-2 border-t border-border pt-4">
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-semibold">{t("title")}</span>
        {instance && <StatusBadge status={instance.status} />}
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">{t("loading")}</p>
      ) : isError ? (
        // A non-404 GET (500/network, or a role that can't read instances)
        // must not fall through to the launch state — that would show a Launch
        // button that then errors. Offer a retry instead.
        <div className="grid gap-2">
          <p className="text-sm text-destructive">{t("loadError")}</p>
          <Button
            type="button"
            variant="outline"
            className="w-fit"
            onClick={() => refetch()}
          >
            {t("retry")}
          </Button>
        </div>
      ) : !instance || instance.status === "destroyed" ? (
        <div className="grid gap-2">
          <p className="text-sm text-muted-foreground">{t("intro")}</p>
          <Button
            type="button"
            className="w-fit"
            onClick={onLaunch}
            disabled={launch.isPending}
          >
            {launch.isPending ? t("launching") : t("launch")}
          </Button>
        </div>
      ) : instance.status === "failed" ? (
        <div className="grid gap-2">
          <p className="text-sm text-destructive">
            {instance.failure_reason || t("failed")}
          </p>
          <Button
            type="button"
            className="w-fit"
            onClick={onLaunch}
            disabled={launch.isPending}
          >
            {launch.isPending ? t("launching") : t("launchAgain")}
          </Button>
        </div>
      ) : ACTIVE_PENDING.has(instance.status) ? (
        <p className="text-sm text-muted-foreground">{t("provisioning")}</p>
      ) : (
        <RunningInstance
          instance={instance}
          onExpired={handleExpired}
          onExtend={onExtend}
          onDestroy={onDestroy}
          extending={extend.isPending}
          destroying={destroy.isPending}
        />
      )}
    </div>
  );
}

function RunningInstance({
  instance,
  onExpired,
  onExtend,
  onDestroy,
  extending,
  destroying,
}: {
  instance: Instance;
  onExpired: () => void;
  onExtend: () => void;
  onDestroy: () => void;
  extending: boolean;
  destroying: boolean;
}) {
  const t = useTranslations("challenges.instance");
  const seconds = useCountdown(instance.expires_at);

  // Self-correct if the `instance_expired` activity ping is missed (WS drop
  // spanning the reap): once the countdown crosses zero, refetch so a
  // reaped instance stops showing stale "running" endpoints. `expired` is a
  // stable boolean, so this fires once per crossing, not every tick.
  const expired = seconds === 0;
  useEffect(() => {
    if (expired) onExpired();
  }, [expired, onExpired]);

  return (
    <div className="grid gap-2">
      {instance.endpoints.length > 0 ? (
        instance.endpoints.map((ep, i) => (
          <CopyLine key={i} value={endpointText(ep)} />
        ))
      ) : (
        <p className="text-sm text-muted-foreground">{t("noEndpoints")}</p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        {seconds !== null && (
          <span className="text-xs text-muted-foreground">
            {t("expiresIn", { time: formatCountdown(seconds) })}
          </span>
        )}
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={onExtend}
          disabled={extending}
        >
          {extending ? t("extending") : t("extend")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="text-destructive"
          onClick={onDestroy}
          disabled={destroying}
        >
          {destroying ? t("destroying") : t("destroy")}
        </Button>
      </div>
    </div>
  );
}

/** A monospace connection line with a copy button, matching ChallengeConnection. */
function CopyLine({ value }: { value: string }) {
  const t = useTranslations("challenges.instance");
  const [copied, setCopied] = useState(false);

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast(t("copyError"), { variant: "destructive" });
    }
  }

  return (
    <div className="flex items-center gap-2">
      <p className="w-fit break-all rounded-md bg-muted px-3 py-1.5 font-mono text-sm">
        {value}
      </p>
      <Button type="button" size="sm" variant="outline" onClick={onCopy}>
        {copied ? t("copied") : t("copy")}
      </Button>
    </div>
  );
}

function StatusBadge({ status }: { status: Instance["status"] }) {
  const t = useTranslations("challenges.instance");
  const variant =
    status === "running"
      ? "success"
      : status === "failed"
        ? "destructive"
        : "muted";
  return <Badge variant={variant}>{t(`status.${status}`)}</Badge>;
}
