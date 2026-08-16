"use client";

// Staff survey builder (ROADMAP #22, feedback_manage): edit survey meta +
// open/close, and add/edit/delete/reorder questions. Question operations are
// immediate (per-question endpoints), so the dialog reflects the live survey
// passed in rather than diffing a draft.

import { useTranslations } from "next-intl";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  useAddQuestion,
  useDeleteQuestion,
  useReorderQuestions,
  useUpdateQuestion,
  useUpdateSurvey,
} from "@/lib/hooks/use-feedback";
import type { QuestionInput, QuestionType, SurveyDetail, SurveyQuestion } from "@/lib/types";
import { toast } from "@/stores/toast";

const TEXTAREA_CLASS =
  "flex min-h-16 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

// The displayed labels live in feedback.types.* (resolved with t() at render);
// this is just their order in the type picker.
const QUESTION_TYPES: QuestionType[] = [
  "rating_1_10",
  "rating_1_5",
  "short_text",
  "long_text",
  "multiple_choice",
];

export function SurveyEditorDialog({
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
  // Seeded on mount: the loader renders this dialog only while open and keys
  // it by survey id, so opening (or switching survey) remounts with fresh
  // fields. Refetches of the same survey deliberately don't clobber edits.
  const t = useTranslations("feedback");
  const [title, setTitle] = React.useState(survey.title);
  const [description, setDescription] = React.useState(survey.description ?? "");
  const [isOpen, setIsOpen] = React.useState(survey.is_open);
  const [editingId, setEditingId] = React.useState<string | null>(null);
  const [adding, setAdding] = React.useState(false);

  const updateSurvey = useUpdateSurvey(competitionId);
  const addQuestion = useAddQuestion(competitionId, survey.id);
  const updateQuestion = useUpdateQuestion(competitionId, survey.id);
  const deleteQuestion = useDeleteQuestion(competitionId, survey.id);
  const confirm = useConfirm();
  const reorder = useReorderQuestions(competitionId, survey.id);

  function saveDetails() {
    updateSurvey.mutate(
      { surveyId: survey.id, input: { title, description: description || null, is_open: isOpen } },
      {
        onSuccess: () => toast(t("editor.savedToast"), { variant: "success" }),
        onError: (e) => toast(t("editor.saveError"), { description: (e as Error).message, variant: "destructive" }),
      },
    );
  }

  function move(index: number, delta: number) {
    const ids = survey.questions.map((q) => q.id);
    const target = index + delta;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    reorder.mutate(ids);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] max-w-[52rem] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("editor.title")}</DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="survey-title">{t("editor.surveyTitle")}</Label>
            <Input id="survey-title" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="survey-desc">{t("editor.description")}</Label>
            <textarea
              id="survey-desc"
              className={TEXTAREA_CLASS}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={isOpen} onChange={(e) => setIsOpen(e.target.checked)} />
            {t("editor.openForResponses")}
            <span className="text-xs text-muted-foreground">
              {t("editor.openHint")}
            </span>
          </label>
          <Button size="sm" onClick={saveDetails} disabled={updateSurvey.isPending || !title.trim()}>
            {t("editor.saveDetails")}
          </Button>
        </div>

        <div className="mt-2 space-y-3 border-t border-border pt-4">
          <h3 className="text-sm font-semibold">{t("editor.questions")}</h3>
          {survey.questions.length === 0 && !adding && (
            <p className="text-[13px] text-muted-foreground">{t("editor.noQuestions")}</p>
          )}
          {survey.questions.map((q, i) =>
            editingId === q.id ? (
              <QuestionForm
                key={q.id}
                initial={q}
                onCancel={() => setEditingId(null)}
                onSave={(input) =>
                  updateQuestion.mutate(
                    { questionId: q.id, input },
                    {
                      onSuccess: () => setEditingId(null),
                      onError: (e) => toast(t("editor.saveQuestionError"), { description: (e as Error).message, variant: "destructive" }),
                    },
                  )
                }
              />
            ) : (
              <div key={q.id} className="flex items-start gap-2 rounded-md border border-border p-3">
                <div className="min-w-0 flex-1">
                  <div className="text-sm">{i + 1}. {q.prompt}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <Badge variant="muted">{t(`types.${q.type}`)}</Badge>
                    {q.required && <span>{t("editor.required")}</span>}
                    {q.type === "multiple_choice" && <span>{q.options.join(" · ")}</span>}
                  </div>
                </div>
                <div className="flex flex-shrink-0 items-center gap-1">
                  <IconBtn label={t("editor.moveUp")} disabled={i === 0} onClick={() => move(i, -1)}>↑</IconBtn>
                  <IconBtn label={t("editor.moveDown")} disabled={i === survey.questions.length - 1} onClick={() => move(i, 1)}>↓</IconBtn>
                  <Button size="sm" variant="outline" onClick={() => { setEditingId(q.id); setAdding(false); }}>
                    {t("editor.edit")}
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={async () => {
                      if (
                        await confirm({
                          title: t("editor.deleteQuestionTitle"),
                          description: t("editor.deleteQuestionDescription"),
                          confirmLabel: t("editor.deleteQuestionLabel"),
                        })
                      ) {
                        deleteQuestion.mutate(q.id);
                      }
                    }}
                  >
                    {t("editor.delete")}
                  </Button>
                </div>
              </div>
            ),
          )}

          {adding ? (
            <QuestionForm
              onCancel={() => setAdding(false)}
              onSave={(input) =>
                addQuestion.mutate(input, {
                  onSuccess: () => setAdding(false),
                  onError: (e) => toast(t("editor.addQuestionError"), { description: (e as Error).message, variant: "destructive" }),
                })
              }
            />
          ) : (
            <button
              type="button"
              onClick={() => { setAdding(true); setEditingId(null); }}
              className="text-xs font-medium text-primary hover:underline"
            >
              {t("editor.addQuestion")}
            </button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function QuestionForm({
  initial,
  onSave,
  onCancel,
}: {
  initial?: SurveyQuestion;
  onSave: (input: QuestionInput) => void;
  onCancel: () => void;
}) {
  const t = useTranslations("feedback");
  const [prompt, setPrompt] = React.useState(initial?.prompt ?? "");
  const [type, setType] = React.useState<QuestionType>(initial?.type ?? "rating_1_5");
  const [required, setRequired] = React.useState(initial?.required ?? true);
  const [optionsText, setOptionsText] = React.useState((initial?.options ?? []).join("\n"));

  const options = optionsText.split("\n").map((s) => s.trim()).filter(Boolean);
  const valid = prompt.trim() !== "" && (type !== "multiple_choice" || options.length >= 2);

  return (
    <div className="space-y-2 rounded-md border border-primary/40 bg-background/40 p-3">
      <div className="space-y-1.5">
        <Label className="text-xs">{t("editor.questionLabel")}</Label>
        <Input value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder={t("editor.questionPlaceholder")} />
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Select value={type} onChange={(e) => setType(e.target.value as QuestionType)} className="h-9 w-48">
          {QUESTION_TYPES.map((qt) => (
            <option key={qt} value={qt}>{t(`types.${qt}`)}</option>
          ))}
        </Select>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={required} onChange={(e) => setRequired(e.target.checked)} />
          {t("editor.requiredCheckbox")}
        </label>
      </div>
      {type === "multiple_choice" && (
        <div className="space-y-1.5">
          <Label htmlFor="survey-q-options" className="text-xs">
            {t("editor.optionsLabel")}
          </Label>
          <textarea
            id="survey-q-options"
            className={TEXTAREA_CLASS}
            value={optionsText}
            onChange={(e) => setOptionsText(e.target.value)}
            placeholder={"web\npwn\ncrypto"}
          />
        </div>
      )}
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={!valid}
          onClick={() => onSave({ prompt: prompt.trim(), type, options, required })}
        >
          {t("editor.saveQuestion")}
        </Button>
        <Button size="sm" variant="outline" onClick={onCancel}>{t("editor.cancel")}</Button>
      </div>
    </div>
  );
}

function IconBtn({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-30"
    >
      {children}
    </button>
  );
}
