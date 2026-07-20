"use client";

import { NotWiredNote, SectionHeader } from "@/components/app/section-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { ANALYTICS } from "@/lib/placeholder-data";

// Challenge analytics — Tier 3 (#23), read-only reporting off data captured by
// scoring/hints/tickets. None of that is captured yet, so this is placeholder.
export default function AnalyticsPage() {
  const { data: competition } = useActiveCompetition();

  return (
    <>
      <SectionHeader title="Analytics" subtitle={`${competition?.name ?? ""} · read-only reporting`} />

      <NotWiredNote>
        Per-challenge analytics are Tier&nbsp;3, derived from scoring/hints/ticket
        data that isn&apos;t captured yet. Figures shown are placeholder.
      </NotWiredNote>

      <Card>
        <CardHeader>
          <CardTitle>Per-challenge stats</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Challenge</TableHead>
                <TableHead>Solves</TableHead>
                <TableHead>Completion</TableHead>
                <TableHead>Avg. time</TableHead>
                <TableHead>Hints used</TableHead>
                <TableHead>Tickets</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {ANALYTICS.map((a) => (
                <TableRow key={a.title}>
                  <TableCell className="font-medium">{a.title}</TableCell>
                  <TableCell className="font-mono">{a.solves}</TableCell>
                  <TableCell className="font-mono">{a.completion}</TableCell>
                  <TableCell className="font-mono">{a.avgTime}</TableCell>
                  <TableCell className="font-mono">{a.hints}</TableCell>
                  <TableCell className="font-mono">{a.tickets}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  );
}
