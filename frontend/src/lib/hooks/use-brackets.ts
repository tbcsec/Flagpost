"use client";

// One hook module per domain (§8). Bracket/division assignment — staff-only
// (admin/judge, edit_competition); competitors no longer self-select.

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { bracketsApi } from "@/lib/api";

/** Assign a subject's (team or user) division — admin/judge only. */
export function useSetSubjectBracket(competitionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ subjectId, bracket }: { subjectId: string; bracket: string | null }) =>
      bracketsApi.setForSubject(competitionId, subjectId, bracket),
    onSuccess: () =>
      // The board labels each entry by bracket — refresh it.
      qc.invalidateQueries({ queryKey: ["scoreboard", competitionId] }),
  });
}
