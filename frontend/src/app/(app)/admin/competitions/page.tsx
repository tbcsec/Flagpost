"use client";

import { useEffect, useState } from "react";

import { CreateCompetitionDialog } from "@/components/competitions/create-competition-dialog";
import { NotWiredNote, SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCloneCompetition, useCompetitions } from "@/lib/hooks/use-competitions";
import type { Competition } from "@/lib/types";
import { toast } from "@/stores/toast";

// Admin → Competitions. Listing, creation and cloning are wired. Archive/delete
// have no endpoints yet, so those actions are present-but-disabled per the
// "add the UI, don't fake the feature" rule.
export default function AdminCompetitionsPage() {
  const { data: competitions, isLoading, isError, error } = useCompetitions();
  const [cloning, setCloning] = useState<Competition | null>(null);

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
                      <Button variant="ghost" size="sm" onClick={() => setCloning(c)}>
                        Clone
                      </Button>
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

      <CloneDialog source={cloning} onClose={() => setCloning(null)} />
    </>
  );
}

function CloneDialog({ source, onClose }: { source: Competition | null; onClose: () => void }) {
  const clone = useCloneCompetition();
  const [name, setName] = useState("");

  // Suggest a name when the dialog opens; the admin renames it so there's no
  // "Test", "Test - 1", "Test - 2" pile-up.
  useEffect(() => {
    if (source) setName(`${source.name} (copy)`);
  }, [source]);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!source) return;
    clone.mutate(
      { id: source.id, name },
      {
        onSuccess: (created) => {
          toast(`Cloned to “${created.name}”`, { variant: "success" });
          onClose();
        },
      },
    );
  }

  return (
    <Dialog open={Boolean(source)} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Clone competition</DialogTitle>
          <DialogDescription>
            Copies {source ? <span className="font-medium">{source.name}</span> : "this competition"}
            &apos;s settings, categories, challenges (with flags), hints, files, surveys, and module
            toggles into a fresh competition. Participants, scores, and tickets are not copied, and
            the schedule is left blank for you to set.
          </DialogDescription>
        </DialogHeader>
        <form className="grid gap-4" onSubmit={onSubmit}>
          <div className="grid gap-2">
            <Label htmlFor="clone-name">New competition name</Label>
            <Input
              id="clone-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              autoFocus
            />
          </div>
          {clone.isError && (
            <p className="text-sm text-destructive">{(clone.error as Error).message}</p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={clone.isPending}>
              {clone.isPending ? "Cloning…" : "Clone competition"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
