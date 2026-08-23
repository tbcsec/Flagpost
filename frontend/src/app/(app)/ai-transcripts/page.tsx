"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { NoCompetition } from "@/components/app/no-competition";
import { SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Markdown } from "@/components/ui/markdown";
import { Skeleton } from "@/components/ui/skeleton";
import { relativeTime } from "@/lib/datetime";
import { useAiTranscript, useAiTranscripts } from "@/lib/hooks/use-ai";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useAccess } from "@/lib/hooks/use-permissions";
import { cn } from "@/lib/utils";

// Transcript review (#98, ADR-0023 Phase 3) — the oversight surface for the
// competitor assistant, deliberately separate from the live chat (spec §6). It
// is what turns the behavioural guidance level from "trusted" into "reviewable":
// an organiser can read exactly what the assistant told competitors. Gated on
// ai_view_transcripts (its own grant — competitor content, not analytics).
export default function AiTranscriptsPage() {
  const t = useTranslations("ai.transcripts");
  const { competitionId, data: competition } = useActiveCompetition();
  const access = useAccess();
  const canView = access.has("ai_view_transcripts");
  const transcripts = useAiTranscripts(competitionId, access.ready && canView);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const detail = useAiTranscript(competitionId, selectedId);

  if (!competitionId) return <NoCompetition />;
  if (!access.ready) return <Skeleton className="h-64 w-full" />;
  if (!canView) {
    return (
      <>
        <SectionHeader title={t("title")} subtitle={competition?.name} />
        <EmptyState
          title={t("noAccessTitle")}
          description={t("noAccessDescription")}
        />
      </>
    );
  }

  const rows = transcripts.data ?? [];
  // Client-side filter by participant name — the list already carries every
  // author's display name, so search stays instant with no request per keystroke.
  const q = query.trim().toLowerCase();
  const filtered = q
    ? rows.filter((r) => r.user_display_name.toLowerCase().includes(q))
    : rows;

  return (
    <>
      <SectionHeader
        title={t("title")}
        subtitle={t("subtitle")}
      />

      {transcripts.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : rows.length === 0 ? (
        <EmptyState
          title={t("emptyTitle")}
          description={t("emptyDescription")}
        />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(16rem,1fr)_2fr]">
          <Card className="self-start">
            <CardContent className="p-0">
              <div className="border-b border-border p-3">
                <Input
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t("searchPlaceholder")}
                  aria-label={t("searchAria")}
                />
              </div>
              {filtered.length === 0 ? (
                <p className="px-4 py-6 text-center text-sm text-muted-foreground">
                  {t("noMatch", { query: query.trim() })}
                </p>
              ) : (
                <ul className="divide-y divide-border">
                  {filtered.map((row) => (
                    <li key={row.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedId(row.id)}
                        className={cn(
                          "flex w-full flex-col gap-0.5 px-4 py-3 text-left transition-colors hover:bg-accent/60",
                          selectedId === row.id && "bg-accent",
                        )}
                      >
                        <span className="flex items-baseline justify-between gap-2">
                          <span className="truncate text-sm font-medium">
                            {row.user_display_name}
                          </span>
                          <span className="whitespace-nowrap text-[11px] text-muted-foreground">
                            {relativeTime(row.last_activity_at)}
                          </span>
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {t("messages", { count: row.message_count })}
                          {row.closed_at ? t("closedSuffix") : ""}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card className="self-start">
            <CardContent className="pt-6">
              {!selectedId ? (
                <p className="text-sm text-muted-foreground">
                  {t("selectPrompt")}
                </p>
              ) : detail.isLoading || !detail.data ? (
                <Skeleton className="h-48 w-full" />
              ) : (
                <div className="grid gap-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold">
                      {detail.data.user_display_name}
                    </span>
                    <Badge variant="muted">{t("assistantBadge")}</Badge>
                    {detail.data.closed_at && <Badge variant="outline">{t("closedBadge")}</Badge>}
                  </div>
                  <div className="grid gap-3">
                    {detail.data.messages.map((m) => (
                      <div
                        key={m.id}
                        className={cn(
                          "flex",
                          m.role === "user" ? "justify-end" : "justify-start",
                        )}
                      >
                        <div
                          className={cn(
                            "max-w-[85%] break-words rounded-2xl px-3.5 py-2 text-sm",
                            m.role === "user"
                              ? "whitespace-pre-wrap rounded-br-sm bg-primary/15 text-foreground"
                              : "rounded-bl-sm bg-muted text-foreground",
                          )}
                        >
                          {m.role === "user" ? m.content : <Markdown content={m.content} />}
                          <div className="mt-1 text-[10px] text-muted-foreground">
                            {m.role === "user" ? t("roleCompetitor") : t("roleAssistant")} ·{" "}
                            {relativeTime(m.created_at)}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );
}
