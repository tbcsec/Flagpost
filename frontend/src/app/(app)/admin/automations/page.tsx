"use client";

import * as React from "react";

import { RuleBuilder } from "@/components/automations/rule-builder";
import { SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { relativeTime } from "@/lib/datetime";
import {
  useAutomationCatalog,
  useAutomations,
  useCreateAutomation,
  useDeleteAutomation,
  useToggleAutomation,
  useUpdateAutomation,
} from "@/lib/hooks/use-automations";
import { useAccess } from "@/lib/hooks/use-permissions";
import type { AutomationRule, AutomationRuleInput } from "@/lib/types";
import { toast } from "@/stores/toast";

// Admin → Automations: the GLOBAL rules surface (competition_id = None, §5.1) —
// rules that fire across every competition. Authoring needs the automation
// perms via a *global* assignment (Administrator); the engine is live from
// Phase 1, and this is the §5.5 builder for the global scope.
export default function AdminAutomationsPage() {
  const access = useAccess();
  const canCreate = access.has("automation_create");
  const { data: catalog } = useAutomationCatalog();
  const { data: rules, isLoading } = useAutomations(); // no competition → global
  const { toggle } = useToggleAutomation();
  const del = useDeleteAutomation();
  const create = useCreateAutomation(); // undefined competition → global rule
  const update = useUpdateAutomation();

  const [creating, setCreating] = React.useState(false);
  const [editing, setEditing] = React.useState<AutomationRule | null>(null);

  function submitNew(input: AutomationRuleInput) {
    create.mutate(input, {
      onSuccess: () => {
        toast("Global rule created", { variant: "success" });
        setCreating(false);
      },
      onError: (e) =>
        toast("Couldn't create", { description: (e as Error).message, variant: "destructive" }),
    });
  }
  function submitEdit(input: AutomationRuleInput) {
    if (!editing) return;
    update.mutate(
      { ruleId: editing.id, input },
      {
        onSuccess: () => {
          toast("Global rule saved", { variant: "success" });
          setEditing(null);
        },
        onError: (e) =>
          toast("Couldn't save", { description: (e as Error).message, variant: "destructive" }),
      },
    );
  }

  return (
    <>
      <SectionHeader
        title="Admin — Automations"
        subtitle="Global — platform-wide, not scoped to a competition"
        actions={
          canCreate && catalog ? (
            <Button size="sm" onClick={() => setCreating(true)}>
              New global rule
            </Button>
          ) : undefined
        }
      />

      {isLoading ? (
        <Skeleton className="h-20" />
      ) : !rules || rules.length === 0 ? (
        <Card>
          <CardContent className="p-10 text-center">
            <p className="text-sm text-muted-foreground">
              No global automations yet. Rules created here apply across every competition.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3">
          {rules.map((rule) => (
            <Card key={rule.id}>
              <CardContent className="flex flex-wrap items-center gap-3 p-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">{rule.name}</span>
                    <Badge variant="secondary">global</Badge>
                    {!rule.is_enabled && <Badge variant="muted">disabled</Badge>}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    on <code className="text-foreground">{rule.trigger_type}</code> →{" "}
                    {rule.actions.map((a) => a.type).join(", ")} · fired {rule.trigger_count}×
                    {rule.last_triggered_at && `, last ${relativeTime(rule.last_triggered_at)}`}
                  </div>
                </div>
                <div className="flex flex-shrink-0 gap-2">
                  <Button size="sm" variant="outline" onClick={() => setEditing(rule)}>
                    Edit
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => toggle(rule)}>
                    {rule.is_enabled ? "Disable" : "Enable"}
                  </Button>
                  <Button size="sm" variant="destructive" onClick={() => del.mutate(rule.id)}>
                    Delete
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {catalog && creating && (
        <RuleBuilder
          open={creating}
          onOpenChange={setCreating}
          catalog={catalog}
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
          personal={false}
          initial={editing}
          onSubmit={submitEdit}
          saving={update.isPending}
        />
      )}
    </>
  );
}
