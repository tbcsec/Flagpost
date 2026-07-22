"use client";

import { NotWiredNote, SectionHeader } from "@/components/app/section-header";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAutomations } from "@/lib/hooks/use-automations";

// Admin → Automations: the GLOBAL rules surface (competition_id = None, §5.1).
// The engine is live (Tier 3 Phase 1); this page lists global rules read-only —
// authoring waits on the Phase 3 visual builder (§5.5). Per-competition rules
// live on the competition-scoped /automations page.
export default function AdminAutomationsPage() {
  const { data: rules, isLoading } = useAutomations();

  return (
    <>
      <SectionHeader title="Admin — Automations" subtitle="Global — platform-wide, not scoped to a competition" />
      <NotWiredNote>
        The automation engine is live. This lists global rules; the visual rule
        builder ships in a later phase — until then, rules are created via the
        API.
      </NotWiredNote>
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
                <span className="text-sm font-medium">{rule.name}</span>
                <span className="text-xs text-muted-foreground">
                  on <code className="text-foreground">{rule.trigger_type}</code>{" "}
                  → {rule.actions.map((a) => a.type).join(", ")} · fired{" "}
                  {rule.trigger_count}×
                </span>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
