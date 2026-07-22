"use client";

import { SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { relativeTime } from "@/lib/datetime";
import {
  useAutomations,
  useDeleteAutomation,
  useToggleAutomation,
} from "@/lib/hooks/use-automations";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useAccess } from "@/lib/hooks/use-permissions";
import type { AutomationRule } from "@/lib/types";

// Automations (§5) — Phase 1 scope: the minimal rules list for the active
// competition (its rules + the globals that fire there), with enable/disable
// and delete. Creating/editing goes through the visual builder, which is
// Phase 3 (§5.5) — until then rules are authored via the API.
export default function AutomationsPage() {
  const { data: competition } = useActiveCompetition();
  const access = useAccess();
  const canView = access.has("automation_view");
  const canEdit = access.has("automation_edit");

  const { data: rules, isLoading, isError } = useAutomations(
    competition?.id,
    Boolean(competition) && canView,
  );
  const { toggle } = useToggleAutomation();
  const deleteRule = useDeleteAutomation();

  return (
    <>
      <SectionHeader
        title="Automations"
        subtitle={`${competition?.name ?? ""} · trigger → conditions → actions`}
      />

      {!access.ready || (canView && isLoading) ? (
        <div className="grid gap-3">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
      ) : !canView ? (
        <Card>
          <CardContent className="p-10 text-center">
            <p className="text-sm text-muted-foreground">
              You don&apos;t have access to this competition&apos;s automation
              rules.
            </p>
          </CardContent>
        </Card>
      ) : isError ? (
        <Card>
          <CardContent className="p-10 text-center">
            <p className="text-sm text-muted-foreground">
              The automations module is disabled for this competition.
            </p>
          </CardContent>
        </Card>
      ) : !rules || rules.length === 0 ? (
        <Card>
          <CardContent className="p-10 text-center">
            <p className="text-sm text-muted-foreground">
              No rules yet. The visual rule builder ships in a later phase —
              until then, rules are created via the API.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3">
          {rules.map((rule) => (
            <RuleCard
              key={rule.id}
              rule={rule}
              canEdit={canEdit}
              onToggle={() => toggle(rule)}
              onDelete={() => deleteRule.mutate(rule.id)}
            />
          ))}
        </div>
      )}
    </>
  );
}

function RuleCard({
  rule,
  canEdit,
  onToggle,
  onDelete,
}: {
  rule: AutomationRule;
  canEdit: boolean;
  onToggle: () => void;
  onDelete: () => void;
}) {
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-3 p-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">{rule.name}</span>
            {rule.competition_id === null && (
              <Badge variant="secondary">global</Badge>
            )}
            {!rule.is_enabled && <Badge variant="muted">disabled</Badge>}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>
              on <code className="text-foreground">{rule.trigger_type}</code>
            </span>
            {rule.conditions.length > 0 && (
              <span>
                {rule.conditions.length} condition
                {rule.conditions.length === 1 ? "" : "s"}
              </span>
            )}
            <span>→ {rule.actions.map((a) => a.type).join(", ")}</span>
            <span>
              fired {rule.trigger_count}×
              {rule.last_triggered_at &&
                `, last ${relativeTime(rule.last_triggered_at)}`}
            </span>
          </div>
        </div>
        {canEdit && (
          <div className="flex flex-shrink-0 gap-2">
            <Button size="sm" variant="outline" onClick={onToggle}>
              {rule.is_enabled ? "Disable" : "Enable"}
            </Button>
            <Button size="sm" variant="destructive" onClick={onDelete}>
              Delete
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
