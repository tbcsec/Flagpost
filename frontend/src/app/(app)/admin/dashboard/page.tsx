"use client";

import { NotWiredNote, SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MODULE_STATUS } from "@/lib/placeholder-data";

// Admin → Dashboard. Global platform overview. No aggregate/health endpoints
// exist yet (the module loader is real but doesn't surface status over HTTP),
// so the tiles and module-status list are placeholder.
const GLOBAL_STATS = [
  { label: "Total accounts", value: "—" },
  { label: "Active competitions", value: "—" },
  { label: "Storage usage", value: "—" },
  { label: "Modules", value: "—" },
];

export default function AdminDashboardPage() {
  return (
    <>
      <SectionHeader title="Admin — Dashboard" subtitle="Global — platform-wide, not scoped to a competition" />
      <NotWiredNote>Platform aggregates and module health have no endpoint yet — figures are placeholder.</NotWiredNote>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {GLOBAL_STATS.map((s) => (
          <Card key={s.label}>
            <CardContent className="p-6 text-center">
              <div className="text-xs text-muted-foreground">{s.label}</div>
              <div className="mt-1 font-display text-3xl font-semibold tracking-tight">{s.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Module status</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="grid gap-2.5">
            {MODULE_STATUS.map((m) => (
              <li key={m.name} className="flex justify-between text-sm">
                <span>{m.name}</span>
                <Badge variant={m.variant}>{m.status}</Badge>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </>
  );
}
