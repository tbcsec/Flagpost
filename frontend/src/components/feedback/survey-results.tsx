"use client";

// Survey results (ROADMAP #22, feedback_view_responses): per-question
// aggregates — rating averages + histograms, choice tallies, free-text lists —
// plus the CSV export.

import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useExportSurveyCsv, useSurveyResults } from "@/lib/hooks/use-feedback";
import type { QuestionResults } from "@/lib/types";
import { toast } from "@/stores/toast";

export function SurveyResultsDialog({
  competitionId,
  surveyId,
  open,
  onOpenChange,
}: {
  competitionId: string;
  surveyId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { data, isLoading } = useSurveyResults(competitionId, open ? surveyId : null);
  const exportCsvMutation = useExportSurveyCsv(competitionId);
  const exporting = exportCsvMutation.isPending;

  function exportCsv() {
    exportCsvMutation.mutate(surveyId, {
      onError: (e) =>
        toast("Export failed", { description: (e as Error).message, variant: "destructive" }),
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] max-w-[52rem] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            Results{data ? ` — ${data.title}` : ""}
          </DialogTitle>
        </DialogHeader>

        {isLoading || !data ? (
          <p className="text-sm text-muted-foreground">Loading results…</p>
        ) : data.response_count === 0 ? (
          <p className="text-sm text-muted-foreground">No responses yet.</p>
        ) : (
          <>
            <p className="text-sm text-muted-foreground">
              {data.response_count} response{data.response_count === 1 ? "" : "s"}
            </p>
            <div className="space-y-5">
              {data.questions.map((q) => (
                <QuestionResultView key={q.question_id} q={q} />
              ))}
            </div>
          </>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button
            disabled={exporting || !data || data.response_count === 0}
            onClick={exportCsv}
          >
            {exporting ? "Exporting…" : "Export CSV"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function QuestionResultView({ q }: { q: QuestionResults }) {
  return (
    <div className="space-y-2 border-b border-border pb-4 last:border-0">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium">{q.prompt}</span>
        <span className="whitespace-nowrap text-xs text-muted-foreground">
          {q.answered} answered
          {q.average !== null && ` · avg ${q.average}`}
        </span>
      </div>
      {q.counts && <Histogram counts={q.counts} />}
      {q.texts && (
        <ul className="space-y-1">
          {q.texts.length === 0 ? (
            <li className="text-[13px] text-muted-foreground">No text answers.</li>
          ) : (
            q.texts.map((t, i) => (
              <li key={i} className="rounded-md bg-muted/50 px-2.5 py-1.5 text-[13px]">
                {t}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}

function Histogram({ counts }: { counts: Record<string, number> }) {
  const max = Math.max(1, ...Object.values(counts));
  return (
    <div className="space-y-1">
      {Object.entries(counts).map(([label, n]) => (
        <div key={label} className="flex items-center gap-2 text-xs">
          <span className="w-24 flex-shrink-0 truncate text-right text-muted-foreground">
            {label}
          </span>
          <div className="h-4 flex-1 overflow-hidden rounded bg-muted">
            <div
              className="h-full bg-primary"
              style={{ width: `${(n / max) * 100}%` }}
            />
          </div>
          <span className="w-6 flex-shrink-0 tabular-nums">{n}</span>
        </div>
      ))}
    </div>
  );
}
