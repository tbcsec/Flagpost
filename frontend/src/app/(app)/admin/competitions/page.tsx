"use client";

import { CreateCompetitionDialog } from "@/components/competitions/create-competition-dialog";
import { NotWiredNote, SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCompetitions } from "@/lib/hooks/use-competitions";

// Admin → Competitions. Listing and creation are fully wired. Archive/delete
// have no endpoints yet (only create + update exist), so those actions are
// present-but-disabled per the "add the UI, don't fake the feature" rule.
export default function AdminCompetitionsPage() {
  const { data: competitions, isLoading, isError, error } = useCompetitions();

  return (
    <>
      <SectionHeader title="Admin — Competitions" subtitle="Global — platform-wide, not scoped to a competition" />

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>All competitions</CardTitle>
            <CardDescription>{competitions?.length ?? 0} total</CardDescription>
          </div>
          <CreateCompetitionDialog />
        </CardHeader>
        <CardContent className="space-y-4">
          <NotWiredNote>Archive and delete have no endpoint yet — those actions are disabled.</NotWiredNote>
          {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {isError && <p className="text-sm text-destructive">{(error as Error).message}</p>}
          {competitions && competitions.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Mode</TableHead>
                  <TableHead>Visibility</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {competitions.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="font-medium">{c.name}</TableCell>
                    <TableCell className="capitalize">{c.participation_mode}</TableCell>
                    <TableCell>
                      <Badge variant={c.visibility === "public" ? "success" : "muted"}>
                        {c.visibility}
                      </Badge>
                    </TableCell>
                    <TableCell className="space-x-2 whitespace-nowrap text-right">
                      <Button variant="ghost" size="sm" disabled>Archive</Button>
                      <Button variant="ghost" size="sm" className="text-destructive" disabled>
                        Delete
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  );
}
