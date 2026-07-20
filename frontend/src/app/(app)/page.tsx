"use client";

import { NotWiredNote, SectionHeader } from "@/components/app/section-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { ACTIVITY, ANNOUNCEMENTS } from "@/lib/placeholder-data";

// Dashboard. Ships as a FIXED layout per ROADMAP (Tier 2, #16); the drag-and-
// drop customization layer is explicitly deferred. The stat/activity/
// announcement widgets need endpoints that don't exist yet, so the numbers here
// are placeholder — see docs/UI-INTEGRATION-NOTES.md.
const STATS = [
  { label: "Active competitors now", value: "—" },
  { label: "Recent solves (1h)", value: "—" },
  { label: "Active teams", value: "—" },
  { label: "Open tickets", value: "—" },
];

export default function DashboardPage() {
  const { data: competition } = useActiveCompetition();

  return (
    <>
      <SectionHeader
        title="Dashboard"
        subtitle={`${competition?.name ?? "—"} · operational overview`}
      />

      <NotWiredNote>
        Live stats, activity feed and announcements need endpoints that arrive in
        later phases (scoring, announcements, WebSocket layer). Values shown are
        placeholder. Drag-and-drop customization is deferred (fixed layout for now).
      </NotWiredNote>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {STATS.map((s) => (
          <Card key={s.label}>
            <CardContent className="p-6 text-center">
              <div className="pt-1 text-xs text-muted-foreground">{s.label}</div>
              <div className="mt-1 font-display text-3xl font-semibold tracking-tight">
                {s.value}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Recent activity</CardTitle>
            <CardDescription>Live feed across the competition</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="grid gap-3.5">
              {ACTIVITY.map((ev) => (
                <li key={ev.id} className="flex justify-between gap-3 text-sm">
                  <span>{ev.text}</span>
                  <span className="whitespace-nowrap text-xs text-muted-foreground">{ev.time}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Announcements</CardTitle>
            <CardDescription>Archive, newest first</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="grid gap-3">
              {ANNOUNCEMENTS.map((an) => (
                <li key={an.id} className="grid gap-0.5">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-[13px] font-medium">{an.title}</span>
                    <span className="whitespace-nowrap text-[11px] text-muted-foreground">{an.time}</span>
                  </div>
                  <span className="text-[13px] text-muted-foreground">{an.body}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
