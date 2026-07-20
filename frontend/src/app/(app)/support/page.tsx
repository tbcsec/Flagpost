"use client";

import { useState } from "react";

import { NotWiredNote, SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { TICKETS } from "@/lib/placeholder-data";
import { cn } from "@/lib/utils";

// Support tickets — Tier 2 (#18). No backend yet; placeholder tickets so the
// design is in place for when the module lands.
const FILTERS = ["all", "open", "closed"] as const;

export default function SupportPage() {
  const { data: competition } = useActiveCompetition();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");

  const stats = [
    { label: "All tickets", value: TICKETS.length },
    { label: "Open tickets", value: TICKETS.filter((t) => t.status === "Open").length },
    { label: "Closed tickets", value: TICKETS.filter((t) => t.status === "Closed").length },
    { label: "Avg. time to respond", value: "—" },
  ];

  const visible = TICKETS.filter(
    (t) => filter === "all" || t.status.toLowerCase() === filter,
  );

  return (
    <>
      <SectionHeader
        title="Support"
        subtitle={`${competition?.name ?? ""} · ${TICKETS.filter((t) => t.status === "Open").length} open`}
      />

      <NotWiredNote>Support tickets are a Tier&nbsp;2 feature — data shown is placeholder.</NotWiredNote>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {stats.map((s) => (
          <Card key={s.label}>
            <CardContent className="p-6 text-center">
              <div className="text-xs text-muted-foreground">{s.label}</div>
              <div className="mt-1 font-display text-2xl font-semibold tracking-tight">{s.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="flex gap-2 border-b border-border">
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              "-mb-px border-b-2 px-1 py-2.5 text-sm capitalize transition-colors",
              filter === f
                ? "border-primary font-semibold text-foreground"
                : "border-transparent font-medium text-muted-foreground",
            )}
          >
            {f}
          </button>
        ))}
      </div>

      <Card>
        <CardContent className="pt-5">
          <ul className="grid">
            {visible.map((tk) => (
              <li
                key={tk.id}
                className="flex items-center justify-between gap-3 border-b border-border py-3 last:border-0"
              >
                <div>
                  <div className="text-sm font-medium">{tk.subject}</div>
                  <div className="text-xs text-muted-foreground">
                    {tk.team}
                    {tk.challenge && ` · ${tk.challenge}`}
                  </div>
                </div>
                <Badge variant={tk.status === "Open" ? "destructive" : "muted"}>{tk.status}</Badge>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </>
  );
}
