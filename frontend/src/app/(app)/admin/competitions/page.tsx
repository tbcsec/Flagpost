"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

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

/** The scheduled-deletion date shown in the archive confirm when retention is
 *  on (#26), or null when it isn't. Module-level on purpose: it reads the clock,
 *  and the React Compiler's purity rule (react-hooks/purity) flags Date.now()
 *  anywhere inside the component — even in an event handler. */
function archiveDeletesOn(autoDelete: boolean, retentionDays: number): string | null {
  if (!autoDelete) return null;
  return new Date(Date.now() + retentionDays * 86_400_000).toLocaleString();
}

export default function AdminCompetitionsPage() {
  const t = useTranslations("admin.competitions");
  const { data: competitions, isLoading, isError, error } = useCompetitions();
  const archive = useArchiveCompetition();
  const { data: site } = useSiteSettings();
  const confirm = useConfirm();
  const [cloning, setCloning] = useState<Competition | null>(null);
  const [deleting, setDeleting] = useState<Competition | null>(null);

  async function onArchive(c: Competition) {
    const archived = !c.archived_at;
    // Archiving closes a competition out (hidden from the switcher/lobby);
    // unarchiving is restorative, so only the archive needs a confirm. With
    // retention on (#26) an archive is also a scheduled deletion, so the dialog
    // states the exact date (consent happens there) and asks for an export first.
    const autoDelete = site?.archive_auto_delete ?? false;
    const retentionDays = site?.archive_retention_days ?? DEFAULT_RETENTION_DAYS;
    const deletesOn = archiveDeletesOn(autoDelete, retentionDays);
    const description = deletesOn
      ? t("archiveDeleteDescription", { deletesOn, days: retentionDays })
      : t("archiveKeepDescription");
    if (
      archived &&
      !(await confirm({
        title: t("archiveTitle", { name: c.name }),
        description,
        confirmLabel: t("archiveConfirm"),
        destructive: autoDelete,
      }))
    ) {
      return;
    }
    archive.mutate(
      { id: c.id, archived },
      {
        onSuccess: () =>
          toast(t(archived ? "archivedToast" : "unarchivedToast", { name: c.name })),
        onError: (e) => toast(t("couldntUpdate"), { description: (e as Error).message, variant: "destructive" }),
      },
    );
  }

  return (
    <>
      <SectionHeader title={t("title")} subtitle={t("subtitle")} />

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>{t("allCompetitions")}</CardTitle>
            <CardDescription>{t("totalCount", { count: competitions?.length ?? 0 })}</CardDescription>
          </div>
          <CreateCompetitionDialog />
        </CardHeader>
        <CardContent className="space-y-4">
          {isLoading && <p className="text-sm text-muted-foreground">{t("loading")}</p>}
          {isError && <p role="alert" className="text-sm text-destructive">{(error as Error).message}</p>}
          {competitions && competitions.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("colName")}</TableHead>
                  <TableHead>{t("colMode")}</TableHead>
                  <TableHead>{t("colVisibility")}</TableHead>
                  <TableHead className="text-right">{t("colActions")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {competitions.map((c) => (
                  <TableRow key={c.id} className={c.archived_at ? "opacity-60" : undefined}>
                    <TableCell className="font-medium">
                      {c.name}
                      {c.archived_at && <Badge variant="outline" className="ml-2">{t("archivedBadge")}</Badge>}
                      {c.purge_after && (
                        <span className="ml-2 text-xs text-destructive">
                          {t("deletesOn", { date: new Date(c.purge_after).toLocaleDateString() })}
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
                        {t("clone")}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={archive.isPending}
                        onClick={() => onArchive(c)}
                      >
                        {c.archived_at ? t("unarchive") : t("archive")}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-destructive"
                        onClick={() => setDeleting(c)}
                      >
                        {t("delete")}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <CloneDialog key={cloning?.id ?? "closed"} source={cloning} onClose={() => setCloning(null)} />
      <DeleteDialog target={deleting} onClose={() => setDeleting(null)} />
    </>
  );
}

function DeleteDialog({ target, onClose }: { target: Competition | null; onClose: () => void }) {
  const t = useTranslations("admin.competitions");
  const del = useDeleteCompetition();

  function onConfirm() {
    if (!target) return;
    del.mutate(target.id, {
      onSuccess: () => {
        toast(t("deletedToast", { name: target.name }), { variant: "success" });
        onClose();
      },
      onError: (e) => toast(t("couldntDelete"), { description: (e as Error).message, variant: "destructive" }),
    });
  }

  return (
    <Dialog open={Boolean(target)} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("deleteTitle")}</DialogTitle>
          <DialogDescription>
            {t.rich("deleteDescription", {
              strong: (chunks) => <span className="font-medium">{chunks}</span>,
              name: target?.name ?? "",
            })}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={del.isPending}>
            {del.isPending ? t("deleting") : t("deleteConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CloneDialog({ source, onClose }: { source: Competition | null; onClose: () => void }) {
  const t = useTranslations("admin.competitions");
  const clone = useCloneCompetition();
  // Seeded on mount — the call site keys this dialog by the source competition,
  // so a new clone target remounts it and the suggested name reseeds. The
  // admin renames it so there's no "Test", "Test - 1", "Test - 2" pile-up.
  const [name, setName] = useState(source ? `${source.name} (copy)` : "");

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!source) return;
    clone.mutate(
      { id: source.id, name },
      {
        onSuccess: (created) => {
          toast(t("clonedToast", { name: created.name }), { variant: "success" });
          onClose();
        },
      },
    );
  }

  return (
    <Dialog open={Boolean(source)} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("cloneTitle")}</DialogTitle>
          <DialogDescription>
            {t.rich("cloneDescription", {
              strong: (chunks) => <span className="font-medium">{chunks}</span>,
              name: source?.name ?? "this competition",
            })}
          </DialogDescription>
        </DialogHeader>
        <form className="grid gap-4" onSubmit={onSubmit}>
          <div className="grid gap-2">
            <Label htmlFor="clone-name">{t("newName")}</Label>
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
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={clone.isPending}>
              {clone.isPending ? t("cloning") : t("cloneConfirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
