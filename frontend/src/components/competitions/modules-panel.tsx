"use client";

// Per-competition module management (§11.3). Lives on Competition Settings —
// module state is competition-scoped, so it belongs with the competition's other
// configuration rather than the global Admin section. Lists the full inventory
// (required-core locked, optional toggleable) off GET/PUT
// /api/competitions/{id}/modules, gated on manage_modules (#168).

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useModules, useToggleModule } from "@/lib/hooks/use-modules";
import { useAccess } from "@/lib/hooks/use-permissions";
import type { ModuleState } from "@/lib/types";
import { toast } from "@/stores/toast";

export function ModulesPanel({ competitionId }: { competitionId: string }) {
  const t = useTranslations("settings.modules");
  const access = useAccess();
  const canManage = access.has("manage_modules");
  const modules = useModules(competitionId, canManage);
  const toggle = useToggleModule(competitionId);

  // Managing modules needs manage_modules specifically (#168); hide the section
  // for a manager who can see settings but wasn't granted module management.
  if (!canManage) return null;

  function onToggle(m: ModuleState) {
    const next = !m.enabled;
    toggle.mutate(
      { moduleId: m.id, enabled: next },
      {
        onSuccess: () =>
          toast(t(next ? "toggledOn" : "toggledOff", { name: m.name }), {
            variant: "success",
          }),
        onError: (e) =>
          toast(t("toggleFailed"), {
            description: (e as Error).message,
            variant: "destructive",
          }),
      },
    );
  }

  if (modules.isLoading) return <Skeleton className="h-64 w-full" />;

  const data = modules.data ?? [];
  const optional = data.filter((m) => !m.required_core);
  const core = data.filter((m) => m.required_core);

  return (
    <div className="grid gap-6">
      <ModuleSection
        title={t("optionalTitle")}
        description={t("optionalDescription")}
        modules={optional}
        onToggle={onToggle}
        pending={toggle.isPending}
      />
      <ModuleSection
        title={t("coreTitle")}
        description={t("coreDescription")}
        modules={core}
        onToggle={onToggle}
        pending={toggle.isPending}
      />
    </div>
  );
}

function ModuleSection({
  title,
  description,
  modules,
  onToggle,
  pending,
}: {
  title: string;
  description: string;
  modules: ModuleState[];
  onToggle: (m: ModuleState) => void;
  pending: boolean;
}) {
  const t = useTranslations("settings.modules");
  if (modules.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <p className="text-sm text-muted-foreground">{description}</p>
      </CardHeader>
      <CardContent>
        <ul className="grid">
          {modules.map((m) => (
            <li
              key={m.id}
              className="flex items-center justify-between gap-3 border-b border-border py-3.5 last:border-0"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{m.name}</span>
                  {m.required_core ? (
                    <Badge variant="muted">{t("badgeCore")}</Badge>
                  ) : m.enabled ? (
                    <Badge variant="success">{t("badgeEnabled")}</Badge>
                  ) : (
                    <Badge variant="outline">{t("badgeDisabled")}</Badge>
                  )}
                </div>
                <div className="font-mono text-xs text-muted-foreground">
                  {m.id} · v{m.version}
                </div>
              </div>
              {m.required_core ? (
                <span className="text-xs text-muted-foreground">{t("alwaysOn")}</span>
              ) : (
                <Button
                  variant={m.enabled ? "outline" : "default"}
                  size="sm"
                  onClick={() => onToggle(m)}
                  disabled={pending}
                >
                  {t(m.enabled ? "disable" : "enable")}
                </Button>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
