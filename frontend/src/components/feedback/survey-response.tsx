"use client";

// Competitor survey response form (ROADMAP #22): renders each question with the
// right control for its type and submits one response.

import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSubmitResponse } from "@/lib/hooks/use-feedback";
import type { SurveyDetail, SurveyQuestion } from "@/lib/types";
import { cn } from "@/lib/utils";
import { toast } from "@/stores/toast";

const TEXTAREA_CLASS =
  "flex min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

const RATING_MAX: Record<string, number> = { rating_1_10: 10, rating_1_5: 5 };

export function SurveyResponseDialog({
  competitionId,
  survey,
  open,
  onOpenChange,
}: {
  competitionId: string;
  survey: SurveyDetail;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [values, setValues] = React.useState<Record<string, string>>({});
  const submit = useSubmitResponse(competitionId, survey.id);

  React.useEffect(() => {
    if (open) setValues({});
  }, [open, survey.id]);

  const missingRequired = survey.questions.some(
    (q) => q.required && !(values[q.id] ?? "").trim(),
  );

  function set(id: string, value: string) {
    setValues((v) => ({ ...v, [id]: value }));
  }

  function onSubmit() {
    const answers = Object.entries(values)
      .filter(([, v]) => v.trim() !== "")
      .map(([question_id, value]) => ({ question_id, value }));
    submit.mutate(answers, {
      onSuccess: () => {
        toast("Thanks for your feedback!", { variant: "success" });
        onOpenChange(false);
      },
      onError: (e) =>
        toast("Couldn't submit", { description: (e as Error).message, variant: "destructive" }),
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] max-w-[45rem] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{survey.title}</DialogTitle>
        </DialogHeader>
        {survey.description && (
          <p className="text-sm text-muted-foreground">{survey.description}</p>
        )}

        <div className="space-y-5">
          {survey.questions.map((q, i) => (
            <div key={q.id} className="space-y-2">
              <Label className="text-sm">
                {i + 1}. {q.prompt}
                {q.required && <span className="ml-1 text-destructive">*</span>}
              </Label>
              <QuestionControl
                question={q}
                value={values[q.id] ?? ""}
                onChange={(v) => set(q.id, v)}
                textareaClass={TEXTAREA_CLASS}
              />
            </div>
          ))}
          {survey.questions.length === 0 && (
            <p className="text-sm text-muted-foreground">This survey has no questions yet.</p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={missingRequired || submit.isPending || survey.questions.length === 0}
            onClick={onSubmit}
          >
            {submit.isPending ? "Submitting…" : "Submit"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function QuestionControl({
  question,
  value,
  onChange,
  textareaClass,
}: {
  question: SurveyQuestion;
  value: string;
  onChange: (value: string) => void;
  textareaClass: string;
}) {
  if (question.type in RATING_MAX) {
    const max = RATING_MAX[question.type];
    return (
      <div className="flex flex-wrap gap-1.5">
        {Array.from({ length: max }, (_, i) => String(i + 1)).map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => onChange(n)}
            className={cn(
              "h-9 w-9 rounded-md border text-sm transition-colors",
              value === n
                ? "border-primary bg-primary text-primary-foreground"
                : "border-input hover:bg-accent",
            )}
          >
            {n}
          </button>
        ))}
      </div>
    );
  }
  if (question.type === "multiple_choice") {
    return (
      <div className="space-y-1.5">
        {question.options.map((opt) => (
          <label key={opt} className="flex cursor-pointer items-center gap-2 text-sm">
            <input
              type="radio"
              name={question.id}
              checked={value === opt}
              onChange={() => onChange(opt)}
            />
            {opt}
          </label>
        ))}
      </div>
    );
  }
  if (question.type === "long_text") {
    return (
      <textarea
        className={textareaClass}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  return <Input value={value} onChange={(e) => onChange(e.target.value)} />;
}
