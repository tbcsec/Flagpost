"use client";

// The "Reports" competition-settings tab (#134, ADR-0030). Organiser picks an
// audience preset (or sections) + formats, generates once the competition has
// ended, and downloads from the history as each report finishes rendering.
// Admin surface, so strings stay literals (not next-intl yet — see #248).

import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useCreateReport,
  useDeleteReport,
  useReportCatalog,
  useReports,
} from "@/lib/hooks/use-reports";
import type {
  CompetitionReport,
  CompetitionStatus,
  ReportStatus,
} from "@/lib/types";
import { toast } from "@/stores/toast";

const CHECKBOX = "h-4 w-4 rounded border-border";
const CHECKBOX_STYLE = { accentColor: "hsl(var(--primary))" } as const;

const STATUS_VARIANT: Record<
  ReportStatus,
  "success" | "destructive" | "secondary"
> = {
  ready: "success",
  failed: "destructive",
  pending: "secondary",
  running: "secondary",
};

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function ReportsPanel({
  competitionId,
  status,
}: {
  competitionId: string;
  status: CompetitionStatus;
}) {
  const catalog = useReportCatalog(competitionId);
  const reports = useReports(competitionId);
  const create = useCreateReport(competitionId);
  const remove = useDeleteReport(competitionId);
  const confirm = useConfirm();

  // `sections === null` means "untouched" — fall back to the technical preset the
  // catalog defines (derived, not seeded via an effect).
  const [sections, setSections] = useState<Set<string> | null>(null);
  const [preset, setPreset] = useState<string | null>("technical");
  const [formats, setFormats] = useState<Set<string>>(new Set(["pdf", "html"]));
  const [topN, setTopN] = useState(10);

  const defaultSections = useMemo(
    () =>
      new Set(
        catalog.data?.presets.technical ??
          catalog.data?.sections.map((s) => s.id) ??
          [],
      ),
    [catalog.data],
  );
  const selected = sections ?? defaultSections;
  const ended = status === "ended";

  function applyPreset(name: string) {
    setSections(new Set(catalog.data?.presets[name] ?? []));
    setPreset(name);
  }

  function toggleSection(id: string) {
    setSections((prev) => {
      const next = new Set(prev ?? defaultSections);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setPreset(null); // a manual change is no longer "a preset"
  }

  function toggleFormat(f: string) {
    setFormats((prev) => {
      const next = new Set(prev);
      if (next.has(f)) next.delete(f);
      else next.add(f);
      return next;
    });
  }

  function onGenerate() {
    create.mutate(
      {
        sections: [...selected],
        formats: [...formats],
        preset,
        top_n: Math.max(3, Math.min(100, topN || 10)),
      },
      {
        onSuccess: () =>
          toast("Report generation started", { variant: "success" }),
        onError: (e) =>
          toast("Couldn't start report", {
            description: (e as Error).message,
            variant: "destructive",
          }),
      },
    );
  }

  async function onDelete(report: CompetitionReport) {
    const ok = await confirm({
      title: `Delete report v${report.version}?`,
      description:
        "The generated files are removed. You can regenerate a new version anytime.",
      confirmLabel: "Delete",
    });
    if (!ok) return;
    remove.mutate(report.id, {
      onSuccess: () => toast("Report deleted", { variant: "success" }),
      onError: (e) =>
        toast("Couldn't delete", {
          description: (e as Error).message,
          variant: "destructive",
        }),
    });
  }

  const canGenerate =
    ended && selected.size > 0 && formats.size > 0 && !create.isPending;

  return (
    <div className="grid gap-6">
      <div>
        <h3 className="text-sm font-semibold">Generate a post-event report</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          A branded PDF/HTML summary of the competition — executive summary,
          participation, results, challenge analysis, and support. Pick an
          audience preset or choose sections, then generate.
        </p>
      </div>

      {!ended && (
        <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
          Reports can be generated once the competition has ended.
        </p>
      )}

      {catalog.isLoading && (
        <p className="text-sm text-muted-foreground">Loading options…</p>
      )}
      {catalog.isError && (
        <p role="alert" className="text-sm text-destructive">
          {(catalog.error as Error).message}
        </p>
      )}

      {catalog.data && (
        <div className="grid gap-4">
          <div className="space-y-2">
            <Label>Audience preset</Label>
            <div className="flex flex-wrap gap-2">
              {Object.keys(catalog.data.presets).map((name) => (
                <Button
                  key={name}
                  type="button"
                  size="sm"
                  variant={preset === name ? "default" : "outline"}
                  className="capitalize"
                  onClick={() => applyPreset(name)}
                >
                  {name}
                </Button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <Label>Sections</Label>
            <div className="grid gap-1.5 sm:grid-cols-2">
              {catalog.data.sections.map((s) => (
                <label key={s.id} className="flex items-center gap-2.5 text-sm">
                  <input
                    type="checkbox"
                    className={CHECKBOX}
                    style={CHECKBOX_STYLE}
                    checked={selected.has(s.id)}
                    onChange={() => toggleSection(s.id)}
                  />
                  {s.label}
                </label>
              ))}
            </div>
          </div>

          <div className="flex flex-wrap items-end gap-6">
            <div className="space-y-2">
              <Label>Formats</Label>
              <div className="flex gap-4">
                {catalog.data.formats.map((f) => (
                  <label
                    key={f}
                    className="flex items-center gap-2 text-sm uppercase"
                  >
                    <input
                      type="checkbox"
                      className={CHECKBOX}
                      style={CHECKBOX_STYLE}
                      checked={formats.has(f)}
                      onChange={() => toggleFormat(f)}
                    />
                    {f}
                  </label>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="report-top-n">Standings shown</Label>
              <Input
                id="report-top-n"
                type="number"
                min={3}
                max={100}
                value={topN}
                onChange={(e) => setTopN(Number(e.target.value))}
                className="w-24"
              />
            </div>
          </div>

          <div>
            <Button type="button" onClick={onGenerate} disabled={!canGenerate}>
              {create.isPending ? "Starting…" : "Generate report"}
            </Button>
          </div>
        </div>
      )}

      <div className="space-y-2 border-t border-border pt-4">
        <h3 className="text-sm font-semibold">History</h3>
        {reports.isLoading && (
          <p className="text-sm text-muted-foreground">Loading…</p>
        )}
        {reports.data?.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No reports generated yet.
          </p>
        )}
        {reports.data && reports.data.length > 0 && (
          <ul className="rounded-md border border-border">
            {reports.data.map((r) => (
              <li
                key={r.id}
                className="flex flex-wrap items-center gap-3 border-b border-border px-3 py-3 last:border-0"
              >
                <span className="text-sm font-medium">Version {r.version}</span>
                <Badge variant={STATUS_VARIANT[r.status]} className="capitalize">
                  {r.status}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {fmtDate(r.created_at)}
                </span>
                {r.status === "failed" && r.error && (
                  <span className="text-xs text-destructive">{r.error}</span>
                )}
                <div className="ml-auto flex items-center gap-2">
                  {r.status === "ready" && r.pdf_url && (
                    <Button asChild size="sm" variant="outline">
                      <a href={r.pdf_url} download>
                        PDF
                      </a>
                    </Button>
                  )}
                  {r.status === "ready" && r.html_url && (
                    <Button asChild size="sm" variant="outline">
                      <a href={r.html_url} download>
                        HTML
                      </a>
                    </Button>
                  )}
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => onDelete(r)}
                  >
                    Delete
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
