"use client";

import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useChallengeRatings } from "@/lib/hooks/use-feedback";

// Staff view of post-solve challenge ratings (Phase 9) — which challenges landed
// well. Hidden until at least one rating exists. Read via feedback_view_responses.
export function ChallengeRatingsPanel({ competitionId }: { competitionId: string }) {
  const { data } = useChallengeRatings(competitionId);
  if (!data || data.length === 0) return null;

  return (
    <section className="grid gap-2">
      <div>
        <h2 className="text-lg font-semibold">Challenge ratings</h2>
        <p className="text-sm text-muted-foreground">
          Average competitor rating (1–5) per challenge — highest first.
        </p>
      </div>
      <Card>
        <CardContent className="pt-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Challenge</TableHead>
                <TableHead className="text-right">Average</TableHead>
                <TableHead className="text-right">Ratings</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((r) => (
                <TableRow key={r.challenge_id}>
                  <TableCell className="font-medium">{r.title}</TableCell>
                  <TableCell className="text-right">
                    <span className="text-primary">★</span> {r.average.toFixed(2)}
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground">{r.count}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </section>
  );
}
