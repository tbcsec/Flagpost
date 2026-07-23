"use client";

import * as React from "react";

import { RuleBuilder } from "@/components/automations/rule-builder";
import { SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { relativeTime } from "@/lib/datetime";
import {
  useAutomationCatalog,
  useAutomations,
  useCreateAutomation,
  useCreatePersonalAutomation,
  useDeleteAutomation,
  useDeletePersonalAutomation,
  usePersonalAutomations,
  useToggleAutomation,
  useUpdateAutomation,
  useUpdatePersonalAutomation,
} from "@/lib/hooks/use-automations";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useAccess } from "@/lib/hooks/use-permissions";
import type { AutomationRule, AutomationRuleInput } from "@/lib/types";
import { toast } from "@/stores/toast";

// Automations (§5) — the wired rule surface: the competition's org rules (with
// the §5.5 visual builder for staff), plus every user's own notify-self
// "personal rules" (§5.1). The engine is live from Phase 1; this is its editor.
export default function AutomationsPage() {
  const { data: competition } = useActiveCompetition();
  const access = useAccess();
  const canView = access.has("automation_view");
  const canCreate = access.has("automation_create");
  const canEdit = access.has("automation_edit");

  const { data: catalog } = useAutomationCatalog(competition?.id);
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

      {/* Org rules — staff only */}
      {canView && (
        <section className="space-y-3">
          {!access.ready || isLoading ? (
            <div className="grid gap-3">
              <Skeleton className="h-20" />
              <Skeleton className="h-20" />
            </div>
          ) : isError ? (
            <EmptyCard>The automations module is disabled for this competition.</EmptyCard>
          ) : (
            <OrgRules
              rules={rules ?? []}
              competitionId={competition?.id}
              catalog={catalog}
              canCreate={canCreate}
              canEdit={canEdit}
              onToggle={(r) => toggle(r)}
              onDelete={(r) => deleteRule.mutate(r.id)}
            />
          )}
        </section>
      )}

      <PersonalRules catalog={catalog} competitionId={competition?.id} />
    </>
  );
}

function OrgRules({
  rules,
  competitionId,
  catalog,
  canCreate,
  canEdit,
  onToggle,
  onDelete,
}: {
  rules: AutomationRule[];
  competitionId?: string;
  catalog: ReturnType<typeof useAutomationCatalog>["data"];
  canCreate: boolean;
  canEdit: boolean;
  onToggle: (r: AutomationRule) => void;
  onDelete: (r: AutomationRule) => void;
}) {
  const [editing, setEditing] = React.useState<AutomationRule | null>(null);
  const [creating, setCreating] = React.useState(false);
  const create = useCreateAutomation(competitionId);
  const update = useUpdateAutomation();

  function submitNew(input: AutomationRuleInput) {
    create.mutate(input, {
      onSuccess: () => {
        toast("Rule created", { variant: "success" });
        setCreating(false);
      },
      onError: (e) =>
        toast("Couldn't create rule", { description: (e as Error).message, variant: "destructive" }),
    });
  }
  function submitEdit(input: AutomationRuleInput) {
    if (!editing) return;
    update.mutate(
      { ruleId: editing.id, input },
      {
        onSuccess: () => {
          toast("Rule saved", { variant: "success" });
          setEditing(null);
        },
        onError: (e) =>
          toast("Couldn't save rule", { description: (e as Error).message, variant: "destructive" }),
      },
    );
  }

  return (
    <>
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Competition rules</h2>
        {canCreate && catalog && (
          <Button size="sm" onClick={() => setCreating(true)}>
            New rule
          </Button>
        )}
      </div>

      {rules.length === 0 ? (
        <EmptyCard>No rules yet. Create one to react to events automatically.</EmptyCard>
      ) : (
        <div className="grid gap-3">
          {rules.map((rule) => (
            <RuleCard
              key={rule.id}
              rule={rule}
              canEdit={canEdit}
              onEdit={() => setEditing(rule)}
              onToggle={() => onToggle(rule)}
              onDelete={() => onDelete(rule)}
            />
          ))}
        </div>
      )}

      {catalog && creating && (
        <RuleBuilder
          open={creating}
          onOpenChange={setCreating}
          catalog={catalog}
          competitionId={competitionId}
          personal={false}
          onSubmit={submitNew}
          saving={create.isPending}
        />
      )}
      {catalog && editing && (
        <RuleBuilder
          open={Boolean(editing)}
          onOpenChange={(o) => !o && setEditing(null)}
          catalog={catalog}
          competitionId={competitionId}
          personal={false}
          initial={editing}
          onSubmit={submitEdit}
          saving={update.isPending}
        />
      )}
    </>
  );
}

function PersonalRules({
  catalog,
  competitionId,
}: {
  catalog: ReturnType<typeof useAutomationCatalog>["data"];
  competitionId?: string;
}) {
  const { data: rules, isLoading } = usePersonalAutomations();
  const create = useCreatePersonalAutomation();
  const update = useUpdatePersonalAutomation();
  const del = useDeletePersonalAutomation();
  const [editing, setEditing] = React.useState<AutomationRule | null>(null);
  const [creating, setCreating] = React.useState(false);

  function submitNew(input: AutomationRuleInput) {
    create.mutate(
      { ...input, competition_id: competitionId ?? null },
      {
        onSuccess: () => {
          toast("Personal rule created", { variant: "success" });
          setCreating(false);
        },
        onError: (e) =>
          toast("Couldn't create", { description: (e as Error).message, variant: "destructive" }),
      },
    );
  }
  function submitEdit(input: AutomationRuleInput) {
    if (!editing) return;
    update.mutate(
      { ruleId: editing.id, input: { ...input, competition_id: editing.competition_id } },
      {
        onSuccess: () => {
          toast("Personal rule saved", { variant: "success" });
          setEditing(null);
        },
        onError: (e) =>
          toast("Couldn't save", { description: (e as Error).message, variant: "destructive" }),
      },
    );
  }

  return (
    <section className="mt-8 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold">My rules</h2>
          <p className="text-xs text-muted-foreground">
            Personal notifications for events you cause — only you see these.
          </p>
        </div>
        {catalog && (
          <Button size="sm" variant="outline" onClick={() => setCreating(true)}>
            New personal rule
          </Button>
        )}
      </div>

      {isLoading ? (
        <Skeleton className="h-16" />
      ) : !rules || rules.length === 0 ? (
        <EmptyCard>No personal rules yet.</EmptyCard>
      ) : (
        <div className="grid gap-3">
          {rules.map((rule) => (
            <RuleCard
              key={rule.id}
              rule={rule}
              canEdit
              onEdit={() => setEditing(rule)}
              onDelete={() => del.mutate(rule.id)}
            />
          ))}
        </div>
      )}

      {catalog && creating && (
        <RuleBuilder
          open={creating}
          onOpenChange={setCreating}
          catalog={catalog}
          competitionId={competitionId}
          personal
          onSubmit={submitNew}
          saving={create.isPending}
        />
      )}
      {catalog && editing && (
        <RuleBuilder
          open={Boolean(editing)}
          onOpenChange={(o) => !o && setEditing(null)}
          catalog={catalog}
          competitionId={competitionId}
          personal
          initial={editing}
          onSubmit={submitEdit}
          saving={update.isPending}
        />
      )}
    </section>
  );
}

function RuleCard({
  rule,
  canEdit,
  onEdit,
  onToggle,
  onDelete,
}: {
  rule: AutomationRule;
  canEdit: boolean;
  onEdit: () => void;
  onToggle?: () => void;
  onDelete: () => void;
}) {
  const confirm = useConfirm();
  async function onDeleteClick() {
    if (
      await confirm({
        title: `Delete "${rule.name}"?`,
        description: "This automation rule will be removed and stop firing.",
        confirmLabel: "Delete rule",
      })
    ) {
      onDelete();
    }
  }
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-3 p-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">{rule.name}</span>
            {rule.competition_id === null && rule.owner_user_id === null && (
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
                {rule.conditions.length} condition{rule.conditions.length === 1 ? "" : "s"}
              </span>
            )}
            <span>→ {rule.actions.map((a) => a.type).join(", ")}</span>
            <span>
              fired {rule.trigger_count}×
              {rule.last_triggered_at && `, last ${relativeTime(rule.last_triggered_at)}`}
            </span>
          </div>
        </div>
        {canEdit && (
          <div className="flex flex-shrink-0 gap-2">
            <Button size="sm" variant="outline" onClick={onEdit}>
              Edit
            </Button>
            {onToggle && (
              <Button size="sm" variant="outline" onClick={onToggle}>
                {rule.is_enabled ? "Disable" : "Enable"}
              </Button>
            )}
            <Button size="sm" variant="destructive" onClick={onDeleteClick}>
              Delete
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function EmptyCard({ children }: { children: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="p-8 text-center">
        <p className="text-sm text-muted-foreground">{children}</p>
      </CardContent>
    </Card>
  );
}
