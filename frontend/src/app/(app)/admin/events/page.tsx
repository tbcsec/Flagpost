"use client";

import { useState } from "react";

import { SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { parseServerDate } from "@/lib/datetime";
import { useAuditEventNames, useAuditLog } from "@/lib/hooks/use-audit-log";
import { useCompetitions } from "@/lib/hooks/use-competitions";
import type { AuditLogQuery } from "@/lib/types";

const PAGE_SIZE = 25;

const EMPTY_DRAFT = {
  q: "",
  event: "",
  competition_id: "",
  team_id: "",
  user_id: "",
  since: "",
  until: "",
};

// datetime-local (local time) → ISO UTC for the API; "" stays undefined.
const toIso = (local: string) => (local ? new Date(local).toISOString() : undefined);
const clean = (v: string) => (v ? v : undefined);

// Admin → Event log (§3.3): a GitLab-issue-style inspector over every event the
// bus emits. Filter by event type (or a `challenge.*` prefix), competition,
// team (matched inside the payload), actor, a time window, and free text; page
// through results; expand a row to read the full payload.
export default function AdminEventLogPage() {
  const [draft, setDraft] = useState({ ...EMPTY_DRAFT });
  const [applied, setApplied] = useState<AuditLogQuery>({
    limit: PAGE_SIZE,
    offset: 0,
  });
  const [expanded, setExpanded] = useState<string | null>(null);

  const eventNames = useAuditEventNames();
  const competitions = useCompetitions();
  const log = useAuditLog(applied);

  const competitionName = (id: string | null) =>
    id ? (competitions.data?.find((c) => c.id === id)?.name ?? id) : "—";

  function set<K extends keyof typeof draft>(key: K, value: string) {
    setDraft((d) => ({ ...d, [key]: value }));
  }

  function applyFilters(e: React.FormEvent) {
    e.preventDefault();
    setApplied({
      q: clean(draft.q),
      event: clean(draft.event),
      competition_id: clean(draft.competition_id),
      team_id: clean(draft.team_id),
      user_id: clean(draft.user_id),
      since: toIso(draft.since),
      until: toIso(draft.until),
      limit: PAGE_SIZE,
      offset: 0,
    });
  }

  function reset() {
    setDraft({ ...EMPTY_DRAFT });
    setApplied({ limit: PAGE_SIZE, offset: 0 });
  }

  const total = log.data?.total ?? 0;
  const offset = applied.offset ?? 0;
  const showingFrom = total === 0 ? 0 : offset + 1;
  const showingTo = Math.min(offset + PAGE_SIZE, total);

  function page(delta: number) {
    setApplied((a) => ({
      ...a,
      offset: Math.max(0, (a.offset ?? 0) + delta * PAGE_SIZE),
    }));
  }

  return (
    <>
      <SectionHeader
        title="Admin — Event log"
        subtitle="Every event the platform emits — global, across all competitions"
      />

      <Card>
        <CardContent className="pt-5">
          <form onSubmit={applyFilters} className="grid gap-3">
            <Input
              placeholder="Search event name or payload…"
              value={draft.q}
              onChange={(e) => set("q", e.target.value)}
            />
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
              <div className="grid gap-1.5">
                <Label htmlFor="f-event">Event type</Label>
                <Select id="f-event" value={draft.event} onChange={(e) => set("event", e.target.value)}>
                  <option value="">All events</option>
                  {eventNames.data?.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="f-comp">Competition</Label>
                <Select
                  id="f-comp"
                  value={draft.competition_id}
                  onChange={(e) => set("competition_id", e.target.value)}
                >
                  <option value="">All competitions</option>
                  {competitions.data?.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="f-team">Team ID</Label>
                <Input id="f-team" value={draft.team_id} onChange={(e) => set("team_id", e.target.value)} />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="f-user">Actor (user ID)</Label>
                <Input id="f-user" value={draft.user_id} onChange={(e) => set("user_id", e.target.value)} />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="f-since">From</Label>
                <Input id="f-since" type="datetime-local" value={draft.since} onChange={(e) => set("since", e.target.value)} />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="f-until">To</Label>
                <Input id="f-until" type="datetime-local" value={draft.until} onChange={(e) => set("until", e.target.value)} />
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button type="submit">Apply filters</Button>
              <Button type="button" variant="ghost" onClick={reset}>
                Reset
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>
          {log.isLoading
            ? "Loading…"
            : `${showingFrom}–${showingTo} of ${total} event(s)`}
        </span>
        <span className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => page(-1)} disabled={offset === 0}>
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => page(1)}
            disabled={showingTo >= total}
          >
            Next
          </Button>
        </span>
      </div>

      {log.isError && (
        <p className="text-sm text-destructive">{(log.error as Error).message}</p>
      )}

      <Card>
        <CardContent className="pt-2">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time (UTC)</TableHead>
                <TableHead>Event</TableHead>
                <TableHead>Competition</TableHead>
                <TableHead>Payload</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {log.data?.items.map((entry) => (
                <TableRow
                  key={entry.id}
                  className="cursor-pointer align-top"
                  onClick={() => setExpanded((id) => (id === entry.id ? null : entry.id))}
                >
                  <TableCell className="whitespace-nowrap font-mono text-xs text-muted-foreground">
                    {parseServerDate(entry.created_at).toISOString().slice(0, 19).replace("T", " ")}
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{entry.event_name}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {competitionName(entry.competition_id)}
                  </TableCell>
                  <TableCell className="min-w-0">
                    {expanded === entry.id ? (
                      <pre className="max-w-xl overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs">
                        {JSON.stringify(entry.payload, null, 2)}
                      </pre>
                    ) : (
                      <span className="line-clamp-1 font-mono text-xs text-muted-foreground">
                        {JSON.stringify(entry.payload)}
                      </span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {log.data && log.data.items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="py-8 text-center text-sm text-muted-foreground">
                    No events match these filters.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  );
}
