"use client";

// One hook module per domain (ARCHITECTURE.md §8). Feedback / surveys
// (ROADMAP #22) — anticipated by §8's `use-feedback.ts` example.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { feedbackApi, ratingsApi } from "@/lib/api";
import type { QuestionInput } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

// --- Challenge ratings (Phase 9, feedback-module extension) ---

/** Submit the current user's 1–5 rating of a solved challenge. Refreshes the
 *  challenge list so `my_rating` updates (and the prompt won't reappear). */
export function useSubmitRating(competitionId: string, challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (rating: number) => ratingsApi.rate(competitionId, challengeId, rating),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["challenges", competitionId] }),
  });
}

/** Per-challenge rating aggregates (staff, Feedback page). */
export function useChallengeRatings(competitionId: string, enabled = true) {
  const authed = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: ["challenge-ratings", competitionId],
    queryFn: () => ratingsApi.summary(competitionId),
    enabled: authed && enabled && Boolean(competitionId),
  });
}

const feedbackKeys = {
  all: (competitionId: string) => ["surveys", competitionId] as const,
  list: (competitionId: string) => ["surveys", competitionId, "list"] as const,
  detail: (competitionId: string, surveyId: string) =>
    ["surveys", competitionId, "detail", surveyId] as const,
  results: (competitionId: string, surveyId: string) =>
    ["surveys", competitionId, "results", surveyId] as const,
};

export function useSurveys(competitionId: string, enabled = true) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: feedbackKeys.list(competitionId),
    queryFn: () => feedbackApi.list(competitionId),
    enabled: enabled && isAuthenticated && Boolean(competitionId),
  });
}

export function useSurvey(competitionId: string, surveyId: string | null) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: feedbackKeys.detail(competitionId, surveyId ?? ""),
    queryFn: () => feedbackApi.get(competitionId, surveyId as string),
    enabled: isAuthenticated && Boolean(competitionId) && Boolean(surveyId),
  });
}

export function useSurveyResults(competitionId: string, surveyId: string | null) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: feedbackKeys.results(competitionId, surveyId ?? ""),
    queryFn: () => feedbackApi.results(competitionId, surveyId as string),
    enabled: isAuthenticated && Boolean(competitionId) && Boolean(surveyId),
  });
}

function useInvalidate(competitionId: string) {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({ queryKey: feedbackKeys.all(competitionId) });
}

export function useCreateSurvey(competitionId: string) {
  const invalidate = useInvalidate(competitionId);
  return useMutation({
    mutationFn: (input: { title: string; description?: string | null }) =>
      feedbackApi.create(competitionId, input),
    onSuccess: invalidate,
  });
}

export function useUpdateSurvey(competitionId: string) {
  const invalidate = useInvalidate(competitionId);
  return useMutation({
    mutationFn: ({
      surveyId,
      input,
    }: {
      surveyId: string;
      input: { title: string; description: string | null; is_open: boolean };
    }) => feedbackApi.update(competitionId, surveyId, input),
    onSuccess: invalidate,
  });
}

export function useDeleteSurvey(competitionId: string) {
  const invalidate = useInvalidate(competitionId);
  return useMutation({
    mutationFn: (surveyId: string) => feedbackApi.remove(competitionId, surveyId),
    onSuccess: invalidate,
  });
}

export function useAddQuestion(competitionId: string, surveyId: string) {
  const invalidate = useInvalidate(competitionId);
  return useMutation({
    mutationFn: (input: QuestionInput) =>
      feedbackApi.addQuestion(competitionId, surveyId, input),
    onSuccess: invalidate,
  });
}

export function useUpdateQuestion(competitionId: string, surveyId: string) {
  const invalidate = useInvalidate(competitionId);
  return useMutation({
    mutationFn: ({ questionId, input }: { questionId: string; input: QuestionInput }) =>
      feedbackApi.updateQuestion(competitionId, surveyId, questionId, input),
    onSuccess: invalidate,
  });
}

export function useDeleteQuestion(competitionId: string, surveyId: string) {
  const invalidate = useInvalidate(competitionId);
  return useMutation({
    mutationFn: (questionId: string) =>
      feedbackApi.removeQuestion(competitionId, surveyId, questionId),
    onSuccess: invalidate,
  });
}

export function useReorderQuestions(competitionId: string, surveyId: string) {
  const invalidate = useInvalidate(competitionId);
  return useMutation({
    mutationFn: (questionIds: string[]) =>
      feedbackApi.reorder(competitionId, surveyId, questionIds),
    onSuccess: invalidate,
  });
}

export function useSubmitResponse(competitionId: string, surveyId: string) {
  const invalidate = useInvalidate(competitionId);
  return useMutation({
    mutationFn: (answers: { question_id: string; value: string }[]) =>
      feedbackApi.submit(competitionId, surveyId, answers),
    onSuccess: invalidate,
  });
}

/** Trigger the CSV download for a survey's responses (§8: the component never
 *  touches the API client directly). */
export function useExportSurveyCsv(competitionId: string) {
  return useMutation({
    mutationFn: (surveyId: string) => feedbackApi.exportCsv(competitionId, surveyId),
  });
}
