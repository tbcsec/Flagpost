"use client";

// Per-competition module management (§11.3). Lives on Competition Settings —
// module state is competition-scoped, so it belongs with the competition's other
// configuration rather than the global Admin section. The full inventory off
// GET/PUT /api/competitions/{id}/modules, gated on manage_modules (#168).
//
// Tiles (#502): the optional modules — the ones an organiser actually chooses
// — first, each with its glyph, a plain-language description and a switch;
// the required-core modules in a quieter, collapsed group below.

import { useTranslations } from "next-intl";
import { useState } from "react";

import { ModuleTile } from "@/components/competitions/module-tile";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useModules, useToggleModule } from "@/lib/hooks/use-modules";
import { useAccess } from "@/lib/hooks/use-permissions";
import type { ModuleState } from "@/lib/types";
import { toast } from "@/stores/toast";

export function ModulesPanel({ competitionId }: { competitionId: string }) {
  const t = useTranslations("settings.modules");
  const catalog = useTranslations("moduleCatalog");
  const access = useAccess();
  const canManage = access.has("manage_modules");
  const modules = useModules(competitionId, canManage);
  const toggle = useToggleModule(competitionId);
  const [showCore, setShowCore] = useState(false);

  // Managing modules needs manage_modules specifically (#168); hide the section
  // for a manager who can see settings but wasn't granted module management.
  if (!canManage) return null;

  function onToggle(m: ModuleState, next: boolean) {
    const key = m.id as "ai";
    const name = catalog.has(`${key}.name`) ? catalog(`${key}.name`) : m.name;
    toggle.mutate(
      { moduleId: m.id, enabled: next },
      {
        onSuccess: () =>
          toast(t(next ? "toggledOn" : "toggledOff", { name }), {
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
      {optional.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t("optionalTitle")}</CardTitle>
            <p className="text-sm text-muted-foreground">{t("optionalDescription")}</p>
          </CardHeader>
          <CardContent>
            {/* Sized by the space the card has, not the viewport — the
                sidebar takes a share of the width at every breakpoint. */}
            <div className="grid grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-3">
              {optional.map((m) => (
                <ModuleTile
                  key={m.id}
                  module={m}
                  enabled={m.enabled}
                  pending={toggle.isPending}
                  onToggle={(next) => onToggle(m, next)}
                />
              ))}
            </div>
          </CardContent>
        </Card>
      )}
      {core.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t("coreTitle")}</CardTitle>
            <p className="text-sm text-muted-foreground">{t("coreDescription")}</p>
          </CardHeader>
          <CardContent className="grid gap-3">
            <Button
              variant="outline"
              size="sm"
              className="justify-self-start"
              aria-expanded={showCore}
              onClick={() => setShowCore(!showCore)}
            >
              {showCore ? t("hideCore") : t("showCore", { count: core.length })}
            </Button>
            {showCore && (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(13rem,1fr))] gap-2">
                {core.map((m) => (
                  <ModuleTile key={m.id} module={m} enabled alwaysOn compact />
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
