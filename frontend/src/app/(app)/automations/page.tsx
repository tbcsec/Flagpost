"use client";

import { useTranslations } from "next-intl";
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
  const t = useTranslations("automations");
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
        title={t("title")}
        subtitle={t("subtitle", { name: competition?.name ?? "" })}
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
            <EmptyCard>{t("moduleDisabled")}</EmptyCard>
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
  const t = useTranslations("automations");
  const [editing, setEditing] = React.useState<AutomationRule | null>(null);
  const [creating, setCreating] = React.useState(false);
  const create = useCreateAutomation(competitionId);
  const update = useUpdateAutomation();

  function submitNew(input: AutomationRuleInput) {
    create.mutate(input, {
      onSuccess: () => {
        toast(t("ruleCreated"), { variant: "success" });
        setCreating(false);
      },
      onError: (e) =>
        toast(t("ruleCreateFailed"), { description: (e as Error).message, variant: "destructive" }),
    });
  }
  function submitEdit(input: AutomationRuleInput) {
    if (!editing) return;
    update.mutate(
      { ruleId: editing.id, input },
      {
        onSuccess: () => {
          toast(t("ruleSaved"), { variant: "success" });
          setEditing(null);
        },
        onError: (e) =>
          toast(t("ruleSaveFailed"), { description: (e as Error).message, variant: "destructive" }),
      },
    );
  }

  return (
    <>
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">{t("competitionRules")}</h2>
        {canCreate && catalog && (
          <Button size="sm" onClick={() => setCreating(true)}>
            {t("newRule")}
          </Button>
        )}
      </div>

      {rules.length === 0 ? (
        <EmptyCard>{t("noRules")}</EmptyCard>
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
  const t = useTranslations("automations");
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
          toast(t("personalCreated"), { variant: "success" });
          setCreating(false);
        },
        onError: (e) =>
          toast(t("personalCreateFailed"), { description: (e as Error).message, variant: "destructive" }),
      },
    );
  }
  function submitEdit(input: AutomationRuleInput) {
    if (!editing) return;
    update.mutate(
      { ruleId: editing.id, input: { ...input, competition_id: editing.competition_id } },
      {
        onSuccess: () => {
          toast(t("personalSaved"), { variant: "success" });
          setEditing(null);
        },
        onError: (e) =>
          toast(t("personalSaveFailed"), { description: (e as Error).message, variant: "destructive" }),
      },
    );
  }

  return (
    <section className="mt-8 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold">{t("myRules")}</h2>
          <p className="text-xs text-muted-foreground">{t("myRulesHint")}</p>
        </div>
        {catalog && (
          <Button size="sm" variant="outline" onClick={() => setCreating(true)}>
            {t("newPersonalRule")}
          </Button>
        )}
      </div>

      {isLoading ? (
        <Skeleton className="h-16" />
      ) : !rules || rules.length === 0 ? (
        <EmptyCard>{t("noPersonalRules")}</EmptyCard>
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
  const t = useTranslations("automations");
  const confirm = useConfirm();
  async function onDeleteClick() {
    if (
      await confirm({
        title: t("deleteConfirmTitle", { name: rule.name }),
        description: t("deleteConfirmDescription"),
        confirmLabel: t("deleteConfirmLabel"),
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
              <Badge variant="secondary">{t("badgeGlobal")}</Badge>
            )}
            {!rule.is_enabled && <Badge variant="muted">{t("badgeDisabled")}</Badge>}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>
              {t("onLabel")} <code className="text-foreground">{rule.trigger_type}</code>
            </span>
            {rule.conditions.length > 0 && (
              <span>{t("conditionCount", { count: rule.conditions.length })}</span>
            )}
            <span>→ {rule.actions.map((a) => a.type).join(", ")}</span>
            <span>
              {t("fired", { count: rule.trigger_count })}
              {rule.last_triggered_at &&
                t("lastFired", { time: relativeTime(rule.last_triggered_at) })}
            </span>
          </div>
        </div>
        {canEdit && (
          <div className="flex flex-shrink-0 gap-2">
            <Button size="sm" variant="outline" onClick={onEdit}>
              {t("edit")}
            </Button>
            {onToggle && (
              <Button size="sm" variant="outline" onClick={onToggle}>
                {rule.is_enabled ? t("disable") : t("enable")}
              </Button>
            )}
            <Button size="sm" variant="destructive" onClick={onDeleteClick}>
              {t("delete")}
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
