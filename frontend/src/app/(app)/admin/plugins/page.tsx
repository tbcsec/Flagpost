"use client";

import { SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useModules, useToggleModule } from "@/lib/hooks/use-modules";
import { useAccess } from "@/lib/hooks/use-permissions";
import type { ModuleState } from "@/lib/types";
import { toast } from "@/stores/toast";

// Admin → Plugins. Module enable/disable is **per-competition** (§11.3), so this
// operates on the active competition (chosen in the topbar switcher). Lists the
// full inventory — required-core modules locked on, optional ones toggleable —
// off GET/PUT /api/competitions/{id}/modules, gated on edit_competition.
export default function AdminPluginsPage() {
  const { competitionId, data: competition } = useActiveCompetition();
  const access = useAccess();
  const canManage = access.has("edit_competition");
  const modules = useModules(competitionId ?? "", Boolean(competitionId) && canManage);
  const toggle = useToggleModule(competitionId ?? "");

  function onToggle(m: ModuleState) {
    const next = !m.enabled;
    toggle.mutate(
      { moduleId: m.id, enabled: next },
      {
        onSuccess: () =>
          toast(`${m.name} ${next ? "enabled" : "disabled"}`, { variant: "success" }),
        onError: (e) =>
          toast("Couldn't update module", {
            description: (e as Error).message,
            variant: "destructive",
          }),
      },
    );
  }

  const data = modules.data ?? [];
  const optional = data.filter((m) => !m.required_core);
  const core = data.filter((m) => m.required_core);

  return (
    <>
      <SectionHeader
        title="Admin — Plugins"
        subtitle={
          competition
            ? `Module availability for ${competition.name} · set per competition`
            : "Module availability — set per competition"
        }
      />

      {!competitionId ? (
        <EmptyState
          title="Select a competition"
          description="Module availability is configured per competition — pick one from the switcher above to manage its modules."
        />
      ) : !access.ready ? (
        <Skeleton className="h-64 w-full" />
      ) : !canManage ? (
        <EmptyState
          title="No access"
          description="You need edit access to this competition to manage its modules."
        />
      ) : modules.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <div className="grid gap-6">
          <ModuleSection
            title="Optional modules"
            description="Disable a module to switch its features off for this competition — its routes stop responding and nothing fires for its events."
            modules={optional}
            onToggle={onToggle}
            pending={toggle.isPending}
          />
          <ModuleSection
            title="Core modules"
            description="Part of the platform floor — always on and can't be disabled."
            modules={core}
            onToggle={onToggle}
            pending={toggle.isPending}
          />
        </div>
      )}
    </>
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
                    <Badge variant="muted">Core</Badge>
                  ) : m.enabled ? (
                    <Badge variant="success">Enabled</Badge>
                  ) : (
                    <Badge variant="outline">Disabled</Badge>
                  )}
                </div>
                <div className="font-mono text-xs text-muted-foreground">
                  {m.id} · v{m.version}
                </div>
              </div>
              {m.required_core ? (
                <span className="text-xs text-muted-foreground">Always on</span>
              ) : (
                <Button
                  variant={m.enabled ? "outline" : "default"}
                  size="sm"
                  onClick={() => onToggle(m)}
                  disabled={pending}
                >
                  {m.enabled ? "Disable" : "Enable"}
                </Button>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
