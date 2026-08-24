"use client";

// Mass user import (#171): upload a roster CSV → dry-run preview of every row
// (create / skip / error, plus the role half) → confirm to commit atomically.
// The preview is the safety step — accounts are hard to un-create, so nothing
// writes until the admin has seen the full per-row report. Passwords travel in
// the file (the CTFd-compatible model), so the copy flags it as sensitive.

import { useTranslations } from "next-intl";
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
  const t = useTranslations("admin.userImport");
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
      toast(t("couldntRead"), {
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
        t("importedToast", { count: report.created }) +
          (report.roles_assigned ? t("importedRolesSuffix", { count: report.roles_assigned }) : ""),
        { variant: "success" },
      );
    } catch (e) {
      toast(t("importFailed"), {
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
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="grid flex-1 gap-1.5">
              <Label htmlFor="user-import-file">{t("csvFile")}</Label>
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
              {t("downloadTemplate")}
            </Button>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="user-import-competition">{t("defaultCompetition")}</Label>
            <Select
              id="user-import-competition"
              value={competitionId}
              disabled={importUsers.isPending}
              onChange={(e) => onCompetitionChange(e.target.value)}
            >
              <option value="">{t("noDefault")}</option>
              {(competitions.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </div>

          {importUsers.isPending && (
            <p className="text-sm text-muted-foreground" role="status">
              {result || preview ? t("working") : t("checkingFile")}
            </p>
          )}

          {report && (
            <div className="grid gap-2">
              <p className="text-sm font-medium">
                {result
                  ? t("doneSummary", { created: result.created, skipped: result.skipped }) +
                    (result.roles_assigned
                      ? t("doneRolesSuffix", { count: result.roles_assigned })
                      : "")
                  : t("previewSummary", {
                      created: report.created,
                      skipped: report.skipped,
                      errors: report.errors,
                    }) +
                    (report.roles_assigned
                      ? t("previewRolesSuffix", { count: report.roles_assigned })
                      : "")}
              </p>
              {report.ignored_columns.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  {t("ignoredColumns", {
                    count: report.ignored_columns.length,
                    columns: report.ignored_columns.join(", "),
                  })}
                </p>
              )}
              <div className="max-h-72 overflow-y-auto rounded-md border border-border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-12">{t("colRow")}</TableHead>
                      <TableHead>{t("colName")}</TableHead>
                      <TableHead>{t("colEmail")}</TableHead>
                      <TableHead>{t("colRole")}</TableHead>
                      <TableHead>{t("colStatus")}</TableHead>
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
              {result ? t("close") : t("cancel")}
            </Button>
            {!result && (
              <Button
                onClick={onConfirm}
                disabled={!preview || importUsers.isPending || preview.created + preview.roles_assigned === 0}
              >
                {importUsers.isPending
                  ? t("importing")
                  : preview
                    ? t("confirmImportCount", { count: preview.created })
                    : t("confirmImport")}
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ImportRowLine({ row, committed }: { row: UserImportRow; committed: boolean }) {
  const t = useTranslations("admin.userImport");
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
              <Badge variant="warning">{t("roleSkipped", { reason: row.role_reason ?? "" })}</Badge>
            )}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell>
        {row.status === "create" ? (
          <Badge variant="success">{committed ? t("createdBadge") : t("willCreate")}</Badge>
        ) : row.status === "skip" ? (
          <Badge variant="muted">{t("skipBadge", { reason: row.reason ?? "" })}</Badge>
        ) : (
          <Badge variant="destructive">{t("errorBadge", { reason: row.reason ?? "" })}</Badge>
        )}
      </TableCell>
    </TableRow>
  );
}
