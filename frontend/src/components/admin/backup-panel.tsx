"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  useBackupSections,
  useExportBackup,
  useImportBackup,
} from "@/lib/hooks/use-site-settings";
import type { BackupDocument, BackupImportResult } from "@/lib/types";
import { toast } from "@/stores/toast";

// Human labels for the backend's section ids (utils/backup.SECTIONS).
const SECTION_LABELS: Record<string, string> = {
  site_settings: "Site settings & branding",
  users: "User accounts",
  roles: "Roles & assignments",
  competitions: "Competitions (challenges, teams, scores, tickets…)",
  automations: "Automation rules",
  audit_log: "Audit log",
};

function label(id: string) {
  return SECTION_LABELS[id] ?? id;
}

function SectionChecklist({
  sections,
  selected,
  onToggle,
}: {
  sections: string[];
  selected: Set<string>;
  onToggle: (id: string, on: boolean) => void;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {sections.map((id) => (
        <label key={id} className="flex items-center gap-2.5 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-border"
            style={{ accentColor: "hsl(var(--primary))" }}
            checked={selected.has(id)}
            onChange={(e) => onToggle(id, e.target.checked)}
          />
          <span>{label(id)}</span>
        </label>
      ))}
    </div>
  );
}

/** Export / import the platform's data (Admin → Site settings). Full-fidelity,
 *  section-selectable; import is additive (adds missing records, never
 *  overwrites or deletes). */
export function BackupPanel() {
  const sections = useBackupSections();
  const exportBackup = useExportBackup();
  const importBackup = useImportBackup();
  const confirm = useConfirm();

  const allSections = useMemo(() => sections.data ?? [], [sections.data]);

  // --- export ---
  const [exportSel, setExportSel] = useState<Set<string>>(new Set());
  // Default every section on once the list loads.
  const exportChosen = exportSel.size || !allSections.length ? exportSel : new Set(allSections);

  function toggleExport(id: string, on: boolean) {
    const next = new Set(exportChosen);
    if (on) next.add(id);
    else next.delete(id);
    setExportSel(next);
  }

  function onExport() {
    exportBackup.mutate([...exportChosen], {
      onSuccess: (doc) => {
        const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "");
        const blob = new Blob([JSON.stringify(doc)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `flagpost-export-${stamp}.json`;
        a.click();
        URL.revokeObjectURL(url);
        toast("Export downloaded", { variant: "success" });
      },
      onError: (e) =>
        toast("Export failed", { description: (e as Error).message, variant: "destructive" }),
    });
  }

  // --- import ---
  const [file, setFile] = useState<BackupDocument | null>(null);
  const [fileName, setFileName] = useState("");
  const [importSel, setImportSel] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<BackupImportResult | null>(null);

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0];
    e.target.value = "";
    setResult(null);
    if (!picked) return;
    try {
      const parsed = JSON.parse(await picked.text()) as BackupDocument;
      if (!parsed?.flagpost_export || !Array.isArray(parsed.sections)) {
        throw new Error("Not a Flagpost export file");
      }
      setFile(parsed);
      setFileName(picked.name);
      setImportSel(new Set(parsed.sections));
    } catch (err) {
      setFile(null);
      setFileName("");
      toast("Couldn't read file", { description: (err as Error).message, variant: "destructive" });
    }
  }

  function toggleImport(id: string, on: boolean) {
    const next = new Set(importSel);
    if (on) next.add(id);
    else next.delete(id);
    setImportSel(next);
  }

  async function onImport() {
    if (!file) return;
    if (
      !(await confirm({
        title: "Import this backup?",
        description: "New records from the selected sections are added to this platform. Existing data is never overwritten or deleted, but this can't be undone selectively.",
        confirmLabel: "Import",
        destructive: false,
      }))
    ) {
      return;
    }
    importBackup.mutate(
      { sections: [...importSel], payload: file },
      {
        onSuccess: (res) => {
          setResult(res);
          const created = Object.values(res).reduce((n, c) => n + c.created, 0);
          toast(`Imported ${created} record${created === 1 ? "" : "s"}`, { variant: "success" });
        },
        onError: (e) =>
          toast("Import failed", { description: (e as Error).message, variant: "destructive" }),
      },
    );
  }

  return (
    <div className="grid max-w-2xl gap-5">
      <Card>
        <CardHeader>
          <CardTitle>Export</CardTitle>
          <CardDescription>
            Download a backup of the selected data as a JSON file. Includes secrets
            (password &amp; flag hashes, SMTP credentials) — store it securely.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <SectionChecklist sections={allSections} selected={exportChosen} onToggle={toggleExport} />
          <Button
            type="button"
            className="w-fit"
            onClick={onExport}
            disabled={exportBackup.isPending || exportChosen.size === 0}
          >
            {exportBackup.isPending ? "Exporting…" : "Export selected"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Import</CardTitle>
          <CardDescription>
            Restore from an export file. <span className="font-medium">Additive</span> — it
            adds records that don&apos;t already exist and never overwrites or deletes
            current data. Existing competitions (matched by name) and users (by
            name/email) are skipped.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <label className="w-fit">
            <span className="inline-flex h-9 cursor-pointer items-center rounded-md border border-border px-3 text-sm font-medium hover:bg-accent/60">
              Choose export file…
            </span>
            <input type="file" accept="application/json,.json" className="hidden" onChange={onFile} />
          </label>

          {file && (
            <>
              <p className="text-xs text-muted-foreground">
                <span className="font-medium text-foreground">{fileName}</span> — exported{" "}
                {file.exported_at ? new Date(file.exported_at).toLocaleString() : "unknown"}
              </p>
              <SectionChecklist sections={file.sections} selected={importSel} onToggle={toggleImport} />
              <Button
                type="button"
                className="w-fit"
                onClick={onImport}
                disabled={importBackup.isPending || importSel.size === 0}
              >
                {importBackup.isPending ? "Importing…" : "Import selected"}
              </Button>
            </>
          )}

          {result && (
            <div className="rounded-md border border-border bg-muted/40 p-3 text-sm">
              <p className="mb-1 font-medium">Import complete</p>
              <ul className="grid gap-0.5 text-xs text-muted-foreground">
                {Object.entries(result)
                  .filter(([, c]) => c.created > 0 || c.skipped > 0)
                  .map(([table, c]) => (
                    <li key={table}>
                      <span className="font-mono">{table}</span>: {c.created} added, {c.skipped} skipped
                    </li>
                  ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
