"use client";

// One hook module per domain (ARCHITECTURE.md §8) for the code judge (#446,
// ADR-0042): the admin site config (Admin → Site settings → Code judge) and
// programming-problem authoring in the challenge editor (#447). The competitor
// surfaces follow in #449.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { judgeAdminApi, judgeProblemApi } from "@/lib/api";
import type {
  JudgeLanguageCreate,
  JudgeLanguageUpdate,
  JudgeProblem,
  JudgeProblemUpdate,
  JudgeSettingsUpdate,
  JudgeTestcaseInput,
} from "@/lib/types";

const judgeKeys = {
  settings: ["judge", "settings"] as const,
  languages: ["judge", "languages"] as const,
  presets: ["judge", "presets"] as const,
};

export function useJudgeSettings() {
  return useQuery({
    queryKey: judgeKeys.settings,
    queryFn: judgeAdminApi.getSettings,
    staleTime: 60_000,
  });
}

export function useUpdateJudgeSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: JudgeSettingsUpdate) => judgeAdminApi.updateSettings(input),
    onSuccess: (data) => queryClient.setQueryData(judgeKeys.settings, data),
  });
}

export function useJudgeLanguages() {
  return useQuery({
    queryKey: judgeKeys.languages,
    queryFn: judgeAdminApi.listLanguages,
    staleTime: 60_000,
  });
}

/** The built-in catalog is static per release, so cache it for the session. */
export function useJudgeLanguagePresets() {
  return useQuery({
    queryKey: judgeKeys.presets,
    queryFn: judgeAdminApi.listPresets,
    staleTime: Infinity,
  });
}

/** Language mutations also refetch settings: whether the judge *can* be
 *  enabled depends on there being an enabled language. */
function useInvalidateJudge() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["judge"] });
}

export function useCreateJudgeLanguage() {
  const invalidate = useInvalidateJudge();
  return useMutation({
    mutationFn: (input: JudgeLanguageCreate) => judgeAdminApi.createLanguage(input),
    onSuccess: invalidate,
  });
}

export function useUpdateJudgeLanguage() {
  const invalidate = useInvalidateJudge();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: JudgeLanguageUpdate }) =>
      judgeAdminApi.updateLanguage(id, input),
    onSuccess: invalidate,
  });
}

export function useDeleteJudgeLanguage() {
  const invalidate = useInvalidateJudge();
  return useMutation({
    mutationFn: (id: string) => judgeAdminApi.deleteLanguage(id),
    onSuccess: invalidate,
  });
}

/** Run the setup flow's connection check against the saved endpoint. Not
 *  cached — it makes live calls, so it only runs on an explicit click. */
export function useCheckJudgeConnection() {
  return useMutation({ mutationFn: () => judgeAdminApi.checkConnection() });
}

export function useApplyJudgeSetup() {
  const invalidate = useInvalidateJudge();
  return useMutation({
    mutationFn: (presetKeys: string[]) => judgeAdminApi.applySetup(presetKeys),
    onSuccess: invalidate,
  });
}

// --- programming problems (#447) ------------------------------------------------

const problemKeys = {
  status: (competitionId: string) => ["judge", "status", competitionId] as const,
  problem: (competitionId: string, challengeId: string) =>
    ["judge", "problem", competitionId, challengeId] as const,
  testcase: (competitionId: string, challengeId: string, testcaseId: string) =>
    ["judge", "problem", competitionId, challengeId, "testcase", testcaseId] as const,
};

/** Can this competition have programming challenges right now, and in which
 *  languages? Drives whether the editor offers the Programming type. */
export function useJudgeStatus(competitionId: string) {
  return useQuery({
    queryKey: problemKeys.status(competitionId),
    queryFn: () => judgeProblemApi.status(competitionId),
    enabled: Boolean(competitionId),
    staleTime: 60_000,
  });
}

export function useJudgeProblem(competitionId: string, challengeId: string) {
  return useQuery({
    queryKey: problemKeys.problem(competitionId, challengeId),
    queryFn: () => judgeProblemApi.get(competitionId, challengeId),
    enabled: Boolean(competitionId) && Boolean(challengeId),
  });
}

/** Full content of one test case, fetched only while its editor is open. */
export function useJudgeTestcase(
  competitionId: string,
  challengeId: string,
  testcaseId: string | null,
) {
  return useQuery({
    queryKey: problemKeys.testcase(competitionId, challengeId, testcaseId ?? ""),
    queryFn: () => judgeProblemApi.getTestcase(competitionId, challengeId, testcaseId!),
    enabled: Boolean(testcaseId),
    staleTime: 0,
  });
}

/** Every problem write answers with the whole problem, so the cache is set
 *  directly (a delete answers with nothing, so it refetches). */
function useProblemWrite<TInput>(
  competitionId: string,
  challengeId: string,
  write: (input: TInput) => Promise<JudgeProblem | void>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: write,
    onSuccess: (data) => {
      if (data) {
        queryClient.setQueryData(problemKeys.problem(competitionId, challengeId), data);
      } else {
        queryClient.invalidateQueries({
          queryKey: problemKeys.problem(competitionId, challengeId),
        });
      }
    },
  });
}

export function useUpdateJudgeProblem(competitionId: string, challengeId: string) {
  return useProblemWrite(competitionId, challengeId, (input: JudgeProblemUpdate) =>
    judgeProblemApi.update(competitionId, challengeId, input),
  );
}

export function useAddJudgeTestcase(competitionId: string, challengeId: string) {
  return useProblemWrite(competitionId, challengeId, (input: JudgeTestcaseInput) =>
    judgeProblemApi.addTestcase(competitionId, challengeId, input),
  );
}

export function useUploadJudgeTestcase(competitionId: string, challengeId: string) {
  return useProblemWrite(
    competitionId,
    challengeId,
    (input: { inputFile: File; answerFile: File; sample: boolean }) =>
      judgeProblemApi.uploadTestcase(competitionId, challengeId, input),
  );
}

export function useUpdateJudgeTestcase(competitionId: string, challengeId: string) {
  return useProblemWrite(
    competitionId,
    challengeId,
    ({ id, input }: { id: string; input: Partial<JudgeTestcaseInput> }) =>
      judgeProblemApi.updateTestcase(competitionId, challengeId, id, input),
  );
}

export function useDeleteJudgeTestcase(competitionId: string, challengeId: string) {
  return useProblemWrite(competitionId, challengeId, (id: string) =>
    judgeProblemApi.deleteTestcase(competitionId, challengeId, id),
  );
}
