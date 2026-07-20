"use client";

import { NotWiredNote, SectionHeader } from "@/components/app/section-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PLUGINS } from "@/lib/placeholder-data";

// Admin → Plugins. The module loader is real (Tier 1 Phase 1) and required-core
// modules register through it, but there's no HTTP surface listing modules or an
// enable/disable admin UI (deferred — no optional module ships in Tier 1).
// Placeholder list.
export default function AdminPluginsPage() {
  return (
    <>
      <SectionHeader title="Admin — Plugins" subtitle="Global — platform-wide, not scoped to a competition" />
      <NotWiredNote>
        The module loader exists, but there&apos;s no endpoint listing modules or
        toggling them — the enable/disable admin UI is deferred. Rows are placeholder.
      </NotWiredNote>

      <Card>
        <CardContent className="pt-5">
          <ul className="grid">
            {PLUGINS.map((pl) => (
              <li
                key={pl.id}
                className="flex items-center justify-between gap-3 border-b border-border py-3.5 last:border-0"
              >
                <div>
                  <div className="text-sm font-medium">{pl.name}</div>
                  <div className="text-xs text-muted-foreground">{pl.description}</div>
                </div>
                <Button variant={pl.enabled ? "outline" : "default"} size="sm" disabled>
                  {pl.enabled ? "Disable" : "Enable"}
                </Button>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </>
  );
}
