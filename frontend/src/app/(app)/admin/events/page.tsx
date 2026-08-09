"use client";

import { Fragment, useState } from "react";

import { SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EntityCombobox } from "@/components/ui/entity-combobox";
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
import { useTeams } from "@/lib/hooks/use-teams";
import { useUsers } from "@/lib/hooks/use-users";
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
  // Name pickers for the id filters: teams are competition-scoped (only load
  // once a competition is chosen); actors come from the global user directory.
  const teams = useTeams(draft.competition_id);
  const users = useUsers("");
  const teamOptions = (teams.data ?? []).map((t) => ({ value: t.id, label: t.name }));
  const userOptions = (users.data ?? []).map((u) => ({
    value: u.id,
    label: u.display_name,
    hint: u.email ?? undefined,
  }));

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
                <Label htmlFor="f-team">Team</Label>
                <EntityCombobox
                  id="f-team"
                  options={teamOptions}
                  value={draft.team_id}
                  onChange={(v) => set("team_id", v)}
                  disabled={!draft.competition_id}
                  placeholder={draft.competition_id ? "Any team" : "Pick a competition first"}
                  emptyText="No teams in this competition"
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="f-user">Actor</Label>
                <EntityCombobox
                  id="f-user"
                  options={userOptions}
                  value={draft.user_id}
                  onChange={(v) => set("user_id", v)}
                  placeholder="Any user"
                />
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
        <p role="alert" className="text-sm text-destructive">{(log.error as Error).message}</p>
      )}

      <Card>
        <CardContent className="pt-2">
          <Table>
            <TableHeader>
              <TableRow>
                {/* w-px pins the metadata columns at their (nowrap) content
                    width so every spare pixel goes to the Payload preview;
                    Competition gets a fixed lane and truncates instead, since
                    a long name shouldn't steal the payload's space either. */}
                <TableHead className="w-px">Time (UTC)</TableHead>
                <TableHead className="w-px">Event</TableHead>
                <TableHead className="w-44">Competition</TableHead>
                <TableHead>Payload</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {log.data?.items.map((entry) => {
                const open = expanded === entry.id;
                const toggle = () =>
                  setExpanded((id) => (id === entry.id ? null : entry.id));
                return (
                  <Fragment key={entry.id}>
                    <TableRow
                      className={
                        open
                          ? "cursor-pointer border-0 bg-muted/30"
                          : "cursor-pointer"
                      }
                      tabIndex={0}
                      aria-expanded={open}
                      aria-controls={open ? `event-payload-${entry.id}` : undefined}
                      onClick={toggle}
                      onKeyDown={(e) => {
                        // Rows aren't natively interactive — mirror a button's
                        // keyboard contract so the toggle isn't mouse-only.
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          toggle();
                        }
                      }}
                    >
                      <TableCell className="whitespace-nowrap font-mono text-xs text-muted-foreground">
                        {parseServerDate(entry.created_at).toISOString().slice(0, 19).replace("T", " ")}
                      </TableCell>
                      <TableCell className="whitespace-nowrap">
                        <Badge variant="secondary">{entry.event_name}</Badge>
                      </TableCell>
                      {/* title recovers what the truncation hides. */}
                      <TableCell
                        className="max-w-44 truncate text-muted-foreground"
                        title={competitionName(entry.competition_id)}
                      >
                        {competitionName(entry.competition_id)}
                      </TableCell>
                      {/* max-w-0 lets the auto-layout table give this column
                          the leftover width instead of sizing it to the
                          payload's full intrinsic width; the inner truncate
                          then clips to that width. Without it a long
                          single-line payload (e.g. competition.updated)
                          stretches the whole table off-screen (#157). */}
                      <TableCell className="max-w-0">
                        <div className="truncate font-mono text-xs text-muted-foreground">
                          {JSON.stringify(entry.payload)}
                        </div>
                      </TableCell>
                    </TableRow>
                    {/* The full payload gets its own row under the entry rather
                        than squeezing into the #157-constrained Payload column.
                        max-w-0 on the colSpan cell keeps this row out of the
                        table's width calculation (the same #157 trick), so a
                        payload with one long unbreakable line scrolls inside
                        the <pre> instead of stretching the table. Not a toggle
                        target, so selecting/copying JSON can't collapse it. */}
                    {open && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell
                          colSpan={4}
                          id={`event-payload-${entry.id}`}
                          className="max-w-0 pt-0"
                        >
                          <pre className="overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs">
                            {JSON.stringify(entry.payload, null, 2)}
                          </pre>
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })}
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
