"use client";

// One hook module per domain (ARCHITECTURE.md §8) for the code judge (#446,
// ADR-0042). This slice (#447) is the admin site config — Admin → Site settings
// → Code judge; problem authoring and the competitor surfaces follow.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { judgeAdminApi } from "@/lib/api";
import type {
  JudgeLanguageCreate,
  JudgeLanguageUpdate,
  JudgeSettingsUpdate,
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
