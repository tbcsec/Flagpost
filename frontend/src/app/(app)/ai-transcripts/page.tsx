"use client";

import { useState } from "react";

import { NoCompetition } from "@/components/app/no-competition";
import { SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
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
  const { competitionId, data: competition } = useActiveCompetition();
  const access = useAccess();
  const canView = access.has("ai_view_transcripts");
  const transcripts = useAiTranscripts(competitionId, access.ready && canView);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const detail = useAiTranscript(competitionId, selectedId);

  if (!competitionId) return <NoCompetition />;
  if (!access.ready) return <Skeleton className="h-64 w-full" />;
  if (!canView) {
    return (
      <>
        <SectionHeader title="AI transcripts" subtitle={competition?.name} />
        <EmptyState
          title="No access"
          description="You need the AI-transcripts permission to review assistant conversations."
        />
      </>
    );
  }

  const rows = transcripts.data ?? [];

  return (
    <>
      <SectionHeader
        title="AI transcripts"
        subtitle="Competitor conversations with the assistant — read-only oversight"
      />

      {transcripts.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No conversations yet"
          description="Competitor chats with the assistant will appear here as they happen."
        />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(16rem,1fr)_2fr]">
          <Card className="self-start">
            <CardContent className="p-0">
              <ul className="divide-y divide-border">
                {rows.map((t) => (
                  <li key={t.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(t.id)}
                      className={cn(
                        "flex w-full flex-col gap-0.5 px-4 py-3 text-left transition-colors hover:bg-accent/60",
                        selectedId === t.id && "bg-accent",
                      )}
                    >
                      <span className="flex items-baseline justify-between gap-2">
                        <span className="truncate text-sm font-medium">
                          {t.user_display_name}
                        </span>
                        <span className="whitespace-nowrap text-[11px] text-muted-foreground">
                          {relativeTime(t.created_at)}
                        </span>
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {t.message_count} message{t.message_count === 1 ? "" : "s"}
                        {t.closed_at ? " · closed" : ""}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <Card className="self-start">
            <CardContent className="pt-6">
              {!selectedId ? (
                <p className="text-sm text-muted-foreground">
                  Select a conversation to read it.
                </p>
              ) : detail.isLoading || !detail.data ? (
                <Skeleton className="h-48 w-full" />
              ) : (
                <div className="grid gap-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold">
                      {detail.data.user_display_name}
                    </span>
                    <Badge variant="muted">competitor assistant</Badge>
                    {detail.data.closed_at && <Badge variant="outline">closed</Badge>}
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
                            "max-w-[85%] whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2 text-sm",
                            m.role === "user"
                              ? "rounded-br-sm bg-primary/15 text-foreground"
                              : "rounded-bl-sm bg-muted text-foreground",
                          )}
                        >
                          {m.content}
                          <div className="mt-1 text-[10px] text-muted-foreground">
                            {m.role === "user" ? "competitor" : "assistant"} ·{" "}
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
