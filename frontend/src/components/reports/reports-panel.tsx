"use client";

// The "Reports" competition-settings tab (#134, ADR-0030). Organiser picks an
// audience preset (or sections) + formats, generates once the competition has
// ended, and downloads from the history as each report finishes rendering.
// Born extracted to next-intl (ADR-0029): new surfaces don't wait for the
// admin-domain sweep (#248).

import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useCreateReport,
  useDeleteReport,
  useDownloadReport,
  useReportCatalog,
  useReports,
} from "@/lib/hooks/use-reports";
import type {
  CompetitionReport,
  CompetitionStatus,
  ReportSection,
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
  const t = useTranslations("reports");
  const catalog = useReportCatalog(competitionId);
  const reports = useReports(competitionId);
  const create = useCreateReport(competitionId);
  const remove = useDeleteReport(competitionId);
  const download = useDownloadReport(competitionId);
  const confirm = useConfirm();

  // Catalog entries localise by id (the survey-editor pattern for
  // backend-defined vocabularies). Unlike those closed enums the catalog is
  // server-extensible, so ids arrive as plain strings rather than typed message
  // keys — `t.has` guards the cast, and an id a newer backend ships before this
  // build knows it falls back to the server's English label, never a raw key
  // path.
  type CatalogKey = Parameters<typeof t.has>[0];
  const keyed = (key: string, fallback: string) =>
    t.has(key as CatalogKey) ? t(key as CatalogKey) : fallback;
  const sectionLabel = (s: ReportSection) => keyed(`sections.${s.id}`, s.label);
  const presetLabel = (name: string) => keyed(`presets.${name}`, name);
  const formatLabel = (format: string) =>
    keyed(`formats.${format}`, format.toUpperCase());

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
          toast(t("generateStartedToast"), { variant: "success" }),
        onError: (e) =>
          toast(t("generateErrorToast"), {
            description: (e as Error).message,
            variant: "destructive",
          }),
      },
    );
  }

  async function onDelete(report: CompetitionReport) {
    const ok = await confirm({
      title: t("deleteConfirm.title", { version: report.version }),
      description: t("deleteConfirm.description"),
      confirmLabel: t("deleteConfirm.confirm"),
    });
    if (!ok) return;
    remove.mutate(report.id, {
      onSuccess: () => toast(t("history.deletedToast"), { variant: "success" }),
      onError: (e) =>
        toast(t("history.deleteErrorToast"), {
          description: (e as Error).message,
          variant: "destructive",
        }),
    });
  }

  function onDownload(report: CompetitionReport, fmt: "pdf" | "html") {
    download.mutate(
      { reportId: report.id, fmt, version: report.version },
      {
        onError: (e) =>
          toast(t("history.downloadErrorToast"), {
            description: (e as Error).message,
            variant: "destructive",
          }),
      },
    );
  }

  const canGenerate =
    ended && selected.size > 0 && formats.size > 0 && !create.isPending;

  return (
    <div className="grid gap-6">
      <div>
        <h3 className="text-sm font-semibold">{t("title")}</h3>
        <p className="mt-1 text-sm text-muted-foreground">{t("intro")}</p>
      </div>

      {!ended && (
        <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
          {t("notEnded")}
        </p>
      )}

      {catalog.isLoading && (
        <p className="text-sm text-muted-foreground">{t("loadingOptions")}</p>
      )}
      {catalog.isError && (
        <p role="alert" className="text-sm text-destructive">
          {(catalog.error as Error).message}
        </p>
      )}

      {catalog.data && (
        <div className="grid gap-4">
          <div className="space-y-2">
            <Label>{t("presetLabel")}</Label>
            <div className="flex flex-wrap gap-2">
              {Object.keys(catalog.data.presets).map((name) => (
                <Button
                  key={name}
                  type="button"
                  size="sm"
                  variant={preset === name ? "default" : "outline"}
                  onClick={() => applyPreset(name)}
                >
                  {presetLabel(name)}
                </Button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <Label>{t("sectionsLabel")}</Label>
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
                  {sectionLabel(s)}
                </label>
              ))}
            </div>
          </div>

          <div className="flex flex-wrap items-end gap-6">
            <div className="space-y-2">
              <Label>{t("formatsLabel")}</Label>
              <div className="flex gap-4">
                {catalog.data.formats.map((f) => (
                  <label key={f} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className={CHECKBOX}
                      style={CHECKBOX_STYLE}
                      checked={formats.has(f)}
                      onChange={() => toggleFormat(f)}
                    />
                    {formatLabel(f)}
                  </label>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="report-top-n">{t("topNLabel")}</Label>
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
              {create.isPending ? t("generateStarting") : t("generate")}
            </Button>
          </div>
        </div>
      )}

      <div className="space-y-2 border-t border-border pt-4">
        <h3 className="text-sm font-semibold">{t("history.title")}</h3>
        {reports.isLoading && (
          <p className="text-sm text-muted-foreground">{t("history.loading")}</p>
        )}
        {reports.data?.length === 0 && (
          <p className="text-sm text-muted-foreground">{t("history.empty")}</p>
        )}
        {reports.data && reports.data.length > 0 && (
          <ul className="rounded-md border border-border">
            {reports.data.map((r) => (
              <li
                key={r.id}
                className="flex flex-wrap items-center gap-3 border-b border-border px-3 py-3 last:border-0"
              >
                <span className="text-sm font-medium">
                  {t("history.version", { version: r.version })}
                </span>
                <Badge variant={STATUS_VARIANT[r.status]}>
                  {t(`history.status.${r.status}`)}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {fmtDate(r.created_at)}
                </span>
                {r.status === "failed" && r.error && (
                  <span className="text-xs text-destructive">{r.error}</span>
                )}
                <div className="ml-auto flex items-center gap-2">
                  {r.status === "ready" && r.pdf_url && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={download.isPending}
                      onClick={() => onDownload(r, "pdf")}
                    >
                      {t("formats.pdf")}
                    </Button>
                  )}
                  {r.status === "ready" && r.html_url && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={download.isPending}
                      onClick={() => onDownload(r, "html")}
                    >
                      {t("formats.html")}
                    </Button>
                  )}
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => onDelete(r)}
                  >
                    {t("history.delete")}
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
