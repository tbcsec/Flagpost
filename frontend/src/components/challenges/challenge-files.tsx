"use client";

// A challenge's files, for competitors: the binaries, archives and handouts an
// author attached — and, for a problem imported from a package (#451), the
// original statement (LaTeX, Markdown or PDF) and its images. Read-only; each
// download goes through a freshly signed, short-lived URL (§13.3). Renders
// nothing when there are no files.

import { useTranslations } from "next-intl";

import { useAttachments, useDownloadAttachment } from "@/lib/hooks/use-attachments";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const fileIcon = (
  <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="7 10 12 15 17 10" />
    <line x1="12" y1="15" x2="12" y2="3" />
  </svg>
);

export function ChallengeFiles({
  competitionId,
  challengeId,
}: {
  competitionId: string;
  challengeId: string;
}) {
  const t = useTranslations("challenges.files");
  const files = useAttachments(competitionId, challengeId);
  const download = useDownloadAttachment(competitionId, challengeId);
  const items = files.data ?? [];
  if (items.length === 0) return null;

  return (
    <section aria-label={t("title")} className="mt-5 space-y-2">
      <h2 className="text-sm font-semibold">{t("title")}</h2>
      <ul className="flex flex-wrap gap-2">
        {items.map((f) => (
          <li key={f.id}>
            <button
              type="button"
              disabled={download.isPending}
              onClick={() => download.mutate(f.id)}
              className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label={t("download", { name: f.filename })}
            >
              <span className="text-muted-foreground">{fileIcon}</span>
              <span className="font-medium">{f.filename}</span>
              <span className="text-xs text-muted-foreground">{formatSize(f.size_bytes)}</span>
            </button>
          </li>
        ))}
      </ul>
      {download.isError && (
        <p role="alert" className="text-sm text-destructive">
          {(download.error as Error).message}
        </p>
      )}
    </section>
  );
}
