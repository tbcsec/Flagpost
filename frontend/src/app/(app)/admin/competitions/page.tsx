"use client";

import { useEffect, useState } from "react";

import { CreateCompetitionDialog } from "@/components/competitions/create-competition-dialog";
import { SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
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
import {
  useArchiveCompetition,
  useCloneCompetition,
  useCompetitions,
  useDeleteCompetition,
} from "@/lib/hooks/use-competitions";
import { useSiteSettings } from "@/lib/hooks/use-site-settings";
import type { Competition } from "@/lib/types";
import { toast } from "@/stores/toast";

// Admin → Competitions: listing, creation, cloning, archive/unarchive and
// delete, all wired.

/** Fallback when site settings haven't loaded — matches the server default. */
const DEFAULT_RETENTION_DAYS = 30;

/** The archive confirm's copy. With retention on (#26) an archive is also a
 *  *scheduled deletion*, so the dialog states the exact date — consent happens
 *  there — and asks for an export first. The server stamps the authoritative
 *  `purge_after`; this is the same now + retention-days arithmetic, previewed.
 *
 *  Module-level on purpose: it reads the clock, and an impure call inside a
 *  component body is a React Compiler purity violation (react-hooks/purity). */
function archiveWarning(
  autoDelete: boolean,
  retentionDays: number,
): { description: string; destructive: boolean } {
  if (!autoDelete) {
    return {
      description:
        "It'll be hidden from the competition switcher and lobby. Its data is kept and you can unarchive it later.",
      destructive: false,
    };
  }
  const deletesOn = new Date(
    Date.now() + retentionDays * 86_400_000,
  ).toLocaleString();
  return {
    description:
      `It'll be hidden from the competition switcher and lobby. ` +
      `Auto-delete is on: it will be permanently deleted on ${deletesOn} ` +
      `(after ${retentionDays} days archived) — database records and stored ` +
      `files. Unarchiving cancels that. Export the competition first if you ` +
      `need the data.`,
    destructive: true,
  };
}

export default function AdminCompetitionsPage() {
  const { data: competitions, isLoading, isError, error } = useCompetitions();
  const archive = useArchiveCompetition();
  const { data: site } = useSiteSettings();
  const confirm = useConfirm();
  const [cloning, setCloning] = useState<Competition | null>(null);
  const [deleting, setDeleting] = useState<Competition | null>(null);

  async function onArchive(c: Competition) {
    const archived = !c.archived_at;
    // Archiving closes a competition out (hidden from the switcher/lobby);
    // unarchiving is restorative, so only the archive needs a confirm.
    const retention = archiveWarning(
      site?.archive_auto_delete ?? false,
      site?.archive_retention_days ?? DEFAULT_RETENTION_DAYS,
    );
    if (
      archived &&
      !(await confirm({
        title: `Archive ${c.name}?`,
        description: retention.description,
        confirmLabel: "Archive",
        destructive: retention.destructive,
      }))
    ) {
      return;
    }
    archive.mutate(
      { id: c.id, archived },
      {
        onSuccess: () => toast(`${c.name} ${archived ? "archived" : "unarchived"}`),
        onError: (e) => toast("Couldn't update", { description: (e as Error).message, variant: "destructive" }),
      },
    );
  }

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
          {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {isError && <p role="alert" className="text-sm text-destructive">{(error as Error).message}</p>}
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
                  <TableRow key={c.id} className={c.archived_at ? "opacity-60" : undefined}>
                    <TableCell className="font-medium">
                      {c.name}
                      {c.archived_at && <Badge variant="outline" className="ml-2">Archived</Badge>}
                      {c.purge_after && (
                        <span className="ml-2 text-xs text-destructive">
                          deletes {new Date(c.purge_after).toLocaleDateString()}
                        </span>
                      )}
                    </TableCell>
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
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={archive.isPending}
                        onClick={() => onArchive(c)}
                      >
                        {c.archived_at ? "Unarchive" : "Archive"}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-destructive"
                        onClick={() => setDeleting(c)}
                      >
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
      <DeleteDialog target={deleting} onClose={() => setDeleting(null)} />
    </>
  );
}

function DeleteDialog({ target, onClose }: { target: Competition | null; onClose: () => void }) {
  const del = useDeleteCompetition();

  function onConfirm() {
    if (!target) return;
    del.mutate(target.id, {
      onSuccess: () => {
        toast(`Deleted ${target.name}`, { variant: "success" });
        onClose();
      },
      onError: (e) => toast("Couldn't delete", { description: (e as Error).message, variant: "destructive" }),
    });
  }

  return (
    <Dialog open={Boolean(target)} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete competition?</DialogTitle>
          <DialogDescription>
            This permanently removes <span className="font-medium">{target?.name}</span> and
            everything under it — challenges, teams, submissions, scores, tickets, surveys. This
            can&apos;t be undone. To just close it out, archive it instead.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={del.isPending}>
            {del.isPending ? "Deleting…" : "Delete competition"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
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
            <p role="alert" className="text-sm text-destructive">{(clone.error as Error).message}</p>
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
