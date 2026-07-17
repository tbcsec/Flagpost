"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCompetitions } from "@/lib/hooks/use-competitions";

export function CompetitionList() {
  const { data, isLoading, isError, error } = useCompetitions();

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading competitions…</p>;
  }
  if (isError) {
    return (
      <p className="text-sm text-destructive">{(error as Error).message}</p>
    );
  }
  if (!data || data.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No competitions yet. Create the first one.
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Mode</TableHead>
          <TableHead>Created</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((competition) => (
          <TableRow key={competition.id}>
            <TableCell className="font-medium">{competition.name}</TableCell>
            <TableCell className="capitalize">
              {competition.participation_mode}
            </TableCell>
            <TableCell className="text-muted-foreground">
              {new Date(competition.created_at).toLocaleDateString()}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
