"use client";

import { NotWiredNote, SectionHeader } from "@/components/app/section-header";
import { Card, CardContent } from "@/components/ui/card";

// Admin → Automations. Global rules. The automation engine is deferred past MVP.
export default function AdminAutomationsPage() {
  return (
    <>
      <SectionHeader title="Admin — Automations" subtitle="Global — platform-wide, not scoped to a competition" />
      <NotWiredNote>The automation engine is deferred past MVP. Placeholder surface.</NotWiredNote>
      <Card>
        <CardContent className="p-10 text-center">
          <p className="text-sm text-muted-foreground">
            No global automations yet. Rules created here apply across every competition.
          </p>
        </CardContent>
      </Card>
    </>
  );
}
