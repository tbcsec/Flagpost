"use client";

import * as React from "react";

import { useTranslations } from "next-intl";

import { SectionHeader } from "@/components/app/section-header";
import { ChallengeRatingsPanel } from "@/components/feedback/challenge-ratings-panel";
import { SurveyEditorDialog } from "@/components/feedback/survey-editor";
import { SurveyResponseDialog } from "@/components/feedback/survey-response";
import { SurveyResultsDialog } from "@/components/feedback/survey-results";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState, SurveyEmptyIcon } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useCreateSurvey,
  useDeleteSurvey,
  useSurvey,
  useSurveys,
} from "@/lib/hooks/use-feedback";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useAccess } from "@/lib/hooks/use-permissions";
import type { SurveySummary } from "@/lib/types";
import { toast } from "@/stores/toast";

// Feedback / surveys (ROADMAP #22). Staff (feedback_manage) build surveys and
// read results; competitors (feedback_submit) answer open ones. The engine's
// survey.submitted trigger fires on submission (Phase 1).
export default function FeedbackPage() {
  const t = useTranslations("feedback");
  const { data: competition } = useActiveCompetition();
  const access = useAccess();
  const isStaff = access.has("feedback_manage");
  const canViewResults = access.has("feedback_view_responses");
  const competitionId = competition?.id;

  const { data: surveys, isLoading, isError } = useSurveys(
    competitionId ?? "",
    Boolean(competitionId) && access.ready,
  );
  const create = useCreateSurvey(competitionId ?? "");
  const del = useDeleteSurvey(competitionId ?? "");
  const confirm = useConfirm();

  // Which survey (id) is open in each dialog, and the mode.
  const [editId, setEditId] = React.useState<string | null>(null);
  const [respondId, setRespondId] = React.useState<string | null>(null);
  const [resultsId, setResultsId] = React.useState<string | null>(null);

  function newSurvey() {
    create.mutate(
      { title: t("untitledSurvey") },
      {
        onSuccess: (survey) => {
          toast(t("createdToast"), { variant: "success" });
          setEditId(survey.id); // open the editor straight away
        },
        onError: (e) => toast(t("createError"), { description: (e as Error).message, variant: "destructive" }),
      },
    );
  }

  return (
    <>
      <SectionHeader
        title={t("title")}
        subtitle={`${competition?.name ?? ""} · ${t("subtitle")}`}
        actions={
          isStaff ? (
            <Button size="sm" onClick={newSurvey} disabled={!competitionId || create.isPending}>
              {t("newSurvey")}
            </Button>
          ) : undefined
        }
      />

      {!access.ready || isLoading ? (
        <div className="grid gap-3">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
      ) : isError ? (
        <Empty>{t("moduleDisabled")}</Empty>
      ) : !surveys || surveys.length === 0 ? (
        <EmptyState
          icon={<SurveyEmptyIcon />}
          title={isStaff ? t("empty.staffTitle") : t("empty.competitorTitle")}
          description={
            isStaff ? t("empty.staffDescription") : t("empty.competitorDescription")
          }
          action={
            isStaff ? (
              <Button onClick={newSurvey} disabled={!competitionId || create.isPending}>
                {t("empty.create")}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="grid gap-3">
          {surveys.map((s) => (
            <SurveyCard
              key={s.id}
              survey={s}
              isStaff={isStaff}
              canViewResults={canViewResults}
              onEdit={() => setEditId(s.id)}
              onRespond={() => setRespondId(s.id)}
              onResults={() => setResultsId(s.id)}
              onDelete={async () => {
                if (
                  await confirm({
                    title: t("card.deleteConfirmTitle", { title: s.title }),
                    description: t("card.deleteConfirmDescription"),
                    confirmLabel: t("card.deleteConfirmLabel"),
                  })
                ) {
                  del.mutate(s.id);
                }
              }}
            />
          ))}
        </div>
      )}

      {canViewResults && competitionId && !isError && (
        <div className="mt-8">
          <ChallengeRatingsPanel competitionId={competitionId} />
        </div>
      )}

      {competitionId && editId && (
        <EditorLoader competitionId={competitionId} surveyId={editId} onClose={() => setEditId(null)} />
      )}
      {competitionId && respondId && (
        <ResponderLoader competitionId={competitionId} surveyId={respondId} onClose={() => setRespondId(null)} />
      )}
      {competitionId && resultsId && (
        <SurveyResultsDialog
          competitionId={competitionId}
          surveyId={resultsId}
          open
          onOpenChange={(o) => !o && setResultsId(null)}
        />
      )}
    </>
  );
}

function SurveyCard({
  survey,
  isStaff,
  canViewResults,
  onEdit,
  onRespond,
  onResults,
  onDelete,
}: {
  survey: SurveySummary;
  isStaff: boolean;
  canViewResults: boolean;
  onEdit: () => void;
  onRespond: () => void;
  onResults: () => void;
  onDelete: () => void;
}) {
  const t = useTranslations("feedback.card");
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-3 p-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">{survey.title}</span>
            <Badge variant={survey.is_open ? "success" : "muted"}>
              {survey.is_open ? t("open") : t("closed")}
            </Badge>
            {survey.responded && <Badge variant="secondary">{t("responded")}</Badge>}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {t("questionCount", { count: survey.question_count })}
            {isStaff && ` · ${t("responseCount", { count: survey.response_count })}`}
          </div>
        </div>
        <div className="flex flex-shrink-0 flex-wrap gap-2">
          {!isStaff && survey.is_open && !survey.responded && (
            <Button size="sm" onClick={onRespond}>{t("respond")}</Button>
          )}
          {isStaff && (
            <>
              <Button size="sm" variant="outline" onClick={onEdit}>{t("edit")}</Button>
              {canViewResults && (
                <Button size="sm" variant="outline" onClick={onResults}>{t("results")}</Button>
              )}
              <Button size="sm" variant="destructive" onClick={onDelete}>{t("delete")}</Button>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// The editor/responder need the full survey (with questions), so fetch detail
// on demand and render the dialog once loaded.
function EditorLoader({
  competitionId,
  surveyId,
  onClose,
}: {
  competitionId: string;
  surveyId: string;
  onClose: () => void;
}) {
  const { data: survey } = useSurvey(competitionId, surveyId);
  if (!survey) return null;
  return (
    <SurveyEditorDialog
      key={survey.id}
      competitionId={competitionId}
      survey={survey}
      open
      onOpenChange={(o) => !o && onClose()}
    />
  );
}

function ResponderLoader({
  competitionId,
  surveyId,
  onClose,
}: {
  competitionId: string;
  surveyId: string;
  onClose: () => void;
}) {
  const { data: survey } = useSurvey(competitionId, surveyId);
  if (!survey) return null;
  return (
    <SurveyResponseDialog
      key={survey.id}
      competitionId={competitionId}
      survey={survey}
      open
      onOpenChange={(o) => !o && onClose()}
    />
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="p-8 text-center">
        <p className="text-sm text-muted-foreground">{children}</p>
      </CardContent>
    </Card>
  );
}
