"use client";

// Mass user import (#171): upload a roster CSV → dry-run preview of every row
// (create / skip / error, plus the role half) → confirm to commit atomically.
// The preview is the safety step — accounts are hard to un-create, so nothing
// writes until the admin has seen the full per-row report. Passwords travel in
// the file (the CTFd-compatible model), so the copy flags it as sensitive.

import { useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { useCompetitions } from "@/lib/hooks/use-competitions";
import { useImportUsers } from "@/lib/hooks/use-users";
import type { UserImportReport, UserImportRow } from "@/lib/types";
import { toast } from "@/stores/toast";

// Matches the backend's accepted columns (utils/user_import.py). role and
// competition are optional; competition is by *name* (ids stay internal).
const TEMPLATE_CSV = [
  "display_name,email,password,role,competition",
  "alice,alice@example.com,changeme-please,Participant,Spring CTF 2026",
  "bob,,another-secret,,",
  "",
].join("\n");

export function UserImportDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const importUsers = useImportUsers();
  const competitions = useCompetitions();
  const fileInput = useRef<HTMLInputElement>(null);
  // Guards rapid re-previews (new file picked while one is in flight): only
  // the latest request may set state, so a slow stale response can't win.
  const previewSeq = useRef(0);

  const [file, setFile] = useState<File | null>(null);
  const [competitionId, setCompetitionId] = useState("");
  const [preview, setPreview] = useState<UserImportReport | null>(null);
  const [result, setResult] = useState<UserImportReport | null>(null);

  function reset() {
    setFile(null);
    setPreview(null);
    setResult(null);
    setCompetitionId("");
    if (fileInput.current) fileInput.current.value = "";
  }

  function close(next: boolean) {
    onOpenChange(next);
    if (!next) reset();
  }

  function downloadTemplate() {
    const url = URL.createObjectURL(new Blob([TEMPLATE_CSV], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "flagpost-users-template.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  async function runPreview(picked: File, defaultCompetitionId: string) {
    const seq = ++previewSeq.current;
    setPreview(null);
    setResult(null);
    try {
      const report = await importUsers.mutateAsync({
        file: picked,
        dryRun: true,
        defaultCompetitionId: defaultCompetitionId || undefined,
      });
      if (seq === previewSeq.current) setPreview(report);
    } catch (e) {
      if (seq !== previewSeq.current) return;
      toast("Couldn't read the file", {
        description: (e as Error).message,
        variant: "destructive",
      });
      reset();
    }
  }

  function onPickFile(picked: File | null) {
    setFile(picked);
    if (picked) void runPreview(picked, competitionId);
  }

  function onCompetitionChange(next: string) {
    setCompetitionId(next);
    // The default competition changes how role rows resolve — re-preview.
    if (file) void runPreview(file, next);
  }

  async function onConfirm() {
    if (!file) return;
    try {
      const report = await importUsers.mutateAsync({
        file,
        dryRun: false,
        defaultCompetitionId: competitionId || undefined,
      });
      setResult(report);
      setPreview(null);
      toast(
        `Imported ${report.created} account${report.created === 1 ? "" : "s"}` +
          (report.roles_assigned ? `, ${report.roles_assigned} role(s) assigned` : ""),
        { variant: "success" },
      );
    } catch (e) {
      toast("Import failed — nothing was created", {
        description: (e as Error).message,
        variant: "destructive",
      });
    }
  }

  const report = result ?? preview;

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-w-[52rem]">
        <DialogHeader>
          <DialogTitle>Import users from CSV</DialogTitle>
          <DialogDescription>
            Upload a roster to create local accounts in bulk, optionally with a
            role per row. Nothing is created until you confirm the preview.
            The file carries plaintext passwords — treat it as sensitive and
            delete it after importing.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="grid flex-1 gap-1.5">
              <Label htmlFor="user-import-file">CSV file</Label>
              <input
                ref={fileInput}
                id="user-import-file"
                type="file"
                accept=".csv,text/csv"
                disabled={importUsers.isPending}
                onChange={(e) => onPickFile(e.target.files?.[0] ?? null)}
                className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-2 file:text-sm file:font-medium file:text-secondary-foreground hover:file:bg-secondary/80"
              />
            </div>
            <Button variant="outline" size="sm" onClick={downloadTemplate}>
              Download template
            </Button>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="user-import-competition">
              Default competition for role rows (optional)
            </Label>
            <Select
              id="user-import-competition"
              value={competitionId}
              disabled={importUsers.isPending}
              onChange={(e) => onCompetitionChange(e.target.value)}
            >
              <option value="">No default — rows name their own</option>
              {(competitions.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </div>

          {importUsers.isPending && (
            <p className="text-sm text-muted-foreground" role="status">
              {result || preview ? "Working…" : "Checking the file…"}
            </p>
          )}

          {report && (
            <div className="grid gap-2">
              <p className="text-sm font-medium">
                {result
                  ? `Done: ${result.created} created, ${result.skipped} skipped` +
                    (result.roles_assigned ? `, ${result.roles_assigned} roles assigned` : "")
                  : `Preview: ${report.created} to create, ${report.skipped} skipped, ` +
                    `${report.errors} error${report.errors === 1 ? "" : "s"}` +
                    (report.roles_assigned ? `, ${report.roles_assigned} roles to assign` : "")}
              </p>
              {report.ignored_columns.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  Ignored column{report.ignored_columns.length === 1 ? "" : "s"}:{" "}
                  {report.ignored_columns.join(", ")}
                </p>
              )}
              <div className="max-h-72 overflow-y-auto rounded-md border border-border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-12">Row</TableHead>
                      <TableHead>Name</TableHead>
                      <TableHead>Email</TableHead>
                      <TableHead>Role</TableHead>
                      <TableHead>Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {report.rows.map((row) => (
                      <ImportRowLine key={row.row} row={row} committed={Boolean(result)} />
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}

          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => close(false)}>
              {result ? "Close" : "Cancel"}
            </Button>
            {!result && (
              <Button
                onClick={onConfirm}
                disabled={!preview || importUsers.isPending || preview.created + preview.roles_assigned === 0}
              >
                {importUsers.isPending
                  ? "Importing…"
                  : `Confirm import${preview ? ` (${preview.created})` : ""}`}
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ImportRowLine({ row, committed }: { row: UserImportRow; committed: boolean }) {
  return (
    <TableRow>
      <TableCell className="text-xs text-muted-foreground">{row.row}</TableCell>
      <TableCell className="font-medium">{row.display_name || "—"}</TableCell>
      <TableCell className="text-muted-foreground">{row.email ?? "—"}</TableCell>
      <TableCell>
        {row.role ? (
          <span className="flex flex-wrap items-center gap-1.5">
            {row.role}
            {row.competition ? (
              <span className="text-xs text-muted-foreground">@ {row.competition}</span>
            ) : null}
            {row.role_action === "skip" && (
              <Badge variant="warning">skipped: {row.role_reason}</Badge>
            )}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell>
        {row.status === "create" ? (
          <Badge variant="success">{committed ? "created" : "will create"}</Badge>
        ) : row.status === "skip" ? (
          <Badge variant="muted">skip: {row.reason}</Badge>
        ) : (
          <Badge variant="destructive">error: {row.reason}</Badge>
        )}
      </TableCell>
    </TableRow>
  );
}
