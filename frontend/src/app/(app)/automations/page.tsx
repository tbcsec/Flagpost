"use client";

import { NotWiredNote, SectionHeader } from "@/components/app/section-header";
import { Card, CardContent } from "@/components/ui/card";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";

// Automations — the full engine (conditions/actions UI, webhooks, personal
// rules) is explicitly deferred past MVP. The event bus it will consume exists
// from Tier 0; the engine does not. This is a placeholder surface.
export default function AutomationsPage() {
  const { data: competition } = useActiveCompetition();

  return (
    <>
      <SectionHeader
        title="Automations"
        subtitle={`${competition?.name ?? ""} · trigger → conditions → actions`}
      />

      <NotWiredNote>
        The automation engine is deferred past MVP (the Tier&nbsp;0 event bus is
        the foundation it will build on). This surface is a placeholder.
      </NotWiredNote>

      <Card>
        <CardContent className="p-10 text-center">
          <p className="text-sm text-muted-foreground">
            No automations yet. Global rules inherited from Admin will appear here, read-only.
          </p>
        </CardContent>
      </Card>
    </>
  );
}
