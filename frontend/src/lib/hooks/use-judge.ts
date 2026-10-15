"use client";

// One hook module per domain (ARCHITECTURE.md §8) for the code judge (#446,
// ADR-0042): the admin site config (Admin → Site settings → Code judge) and
// programming-problem authoring in the challenge editor (#447). The competitor
// surfaces follow in #449.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { judgeAdminApi, judgeProblemApi, judgingsApi, juryApi } from "@/lib/api";
import type {
  JudgingListFilters,
  RejudgeScope,
  CodeSubmitInput,
  Judging,
  JudgeLanguageCreate,
  JudgeLanguageUpdate,
  JudgeProblem,
  JudgeProblemUpdate,
  JudgeSettingsUpdate,
  JudgeTestcaseInput,
  ReferenceCheck,
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
      // A changed test case or limit can put the reference check out of date.
      queryClient.invalidateQueries({ queryKey: referenceKey(competitionId, challengeId) });
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

// --- the reference-solution check (#450) ------------------------------------------------

// Under the ["judge", "judgings", cid] prefix, which a judging's live frame
// refreshes (use-notifications) — so the author's own check updates as it runs.
// The object segment can't collide with a challenge's history key.
const referenceKey = (competitionId: string, challengeId: string) =>
  ["judge", "judgings", competitionId, { reference: challengeId }] as const;

const isActiveCheck = (data: ReferenceCheck | undefined) =>
  data?.judging?.status === "queued" || data?.judging?.status === "running";

/** The problem's latest reference check. Polled while it runs, as a fallback
 *  for a co-author (the live frame goes to whoever started it). */
export function useReferenceCheck(competitionId: string, challengeId: string) {
  return useQuery({
    queryKey: referenceKey(competitionId, challengeId),
    queryFn: () => judgeProblemApi.reference(competitionId, challengeId),
    enabled: Boolean(competitionId) && Boolean(challengeId),
    refetchInterval: (query) => (isActiveCheck(query.state.data) ? 3_000 : false),
  });
}

export function useRunReferenceCheck(competitionId: string, challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { language: string; source: string }) =>
      judgeProblemApi.runReference(competitionId, challengeId, input),
    onSuccess: (data) =>
      queryClient.setQueryData(referenceKey(competitionId, challengeId), data),
  });
}

// --- solving (#449) ------------------------------------------------------------------

export const judgingKeys = {
  problem: (competitionId: string, challengeId: string) =>
    ["judge", "problem-view", competitionId, challengeId] as const,
  mine: (competitionId: string, challengeId: string) =>
    ["judge", "judgings", competitionId, challengeId] as const,
  /** Prefix for every judging read in a competition (live frames invalidate it). */
  competition: (competitionId: string) => ["judge", "judgings", competitionId] as const,
};

const isActive = (j: Judging) => j.status === "queued" || j.status === "running";

/** The problem as a competitor sees it: limits, languages, examples. */
export function useProblemView(competitionId: string, challengeId: string) {
  return useQuery({
    queryKey: judgingKeys.problem(competitionId, challengeId),
    queryFn: () => judgingsApi.problem(competitionId, challengeId),
    enabled: Boolean(competitionId) && Boolean(challengeId),
  });
}

/** This subject's judgings of a challenge, newest first. Live frames on the
 *  user room keep it current (useNotifications); while one is still in flight
 *  it also polls slowly, in case the socket is down. */
export function useMyJudgings(competitionId: string, challengeId: string) {
  return useQuery({
    queryKey: judgingKeys.mine(competitionId, challengeId),
    queryFn: () => judgingsApi.listMine(competitionId, challengeId),
    enabled: Boolean(competitionId) && Boolean(challengeId),
    refetchInterval: (query) => (query.state.data?.some(isActive) ? 5_000 : false),
  });
}

export function useSubmitCode(competitionId: string, challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CodeSubmitInput) => judgingsApi.submit(competitionId, challengeId, input),
    onSuccess: (judging) => {
      queryClient.setQueryData<Judging[]>(judgingKeys.mine(competitionId, challengeId), (prev) => [
        judging,
        ...(prev ?? []).filter((j) => j.id !== judging.id),
      ]);
    },
  });
}

/** A judging's source, fetched only when asked for (loading it into the editor). */
export function useLoadJudgingSource(competitionId: string) {
  return useMutation({
    mutationFn: (judgingId: string) => judgingsApi.source(competitionId, judgingId),
  });
}

// --- the jury console (#450) ------------------------------------------------------------

const juryKeys = {
  all: (competitionId: string) => ["judge", "jury", competitionId] as const,
  list: (competitionId: string, filters: JudgingListFilters) =>
    ["judge", "jury", competitionId, "list", filters] as const,
  queue: (competitionId: string) => ["judge", "jury", competitionId, "queue"] as const,
  history: (competitionId: string, codeSubmissionId: string) =>
    ["judge", "jury", competitionId, "history", codeSubmissionId] as const,
};

// Staff watch other people's judgings, which no socket pushes to them; a short
// poll keeps the console current while it's open.
const JURY_POLL_MS = 5_000;

export function useJudgingList(competitionId: string, filters: JudgingListFilters) {
  return useQuery({
    queryKey: juryKeys.list(competitionId, filters),
    queryFn: () => juryApi.list(competitionId, filters),
    enabled: Boolean(competitionId),
    refetchInterval: JURY_POLL_MS,
  });
}

export function useJudgingQueue(competitionId: string) {
  return useQuery({
    queryKey: juryKeys.queue(competitionId),
    queryFn: () => juryApi.queue(competitionId),
    enabled: Boolean(competitionId),
    refetchInterval: JURY_POLL_MS,
  });
}

// Another staff member's draft problems send no live ping (a draft's
// existence is kept off the activity room), so the sidebar check also
// re-asks now and then — a cheap, staff-only count.
const PROGRAMMING_PROBLEMS_REFRESH_MS = 60_000;

/** Whether the sidebar's Judging entry is worth showing: the competition has
 *  at least one programming problem (drafts included), so a flag-only CTF's
 *  staff never see an empty console. Keyed under the challenge list on purpose
 *  — your own authoring and published-challenge pings refresh that, and so
 *  this, by prefix — with an object segment so it can never be mistaken for a
 *  challenge's detail key (["challenges", cid, id]). */
export function useHasProgrammingProblems(competitionId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["challenges", competitionId, { programmingProblems: true }],
    queryFn: () => juryApi.queue(competitionId),
    select: (queue) => queue.problems > 0,
    enabled: enabled && Boolean(competitionId),
    refetchInterval: PROGRAMMING_PROBLEMS_REFRESH_MS,
  });
}

export function useSubmissionHistory(competitionId: string, codeSubmissionId: string | null) {
  return useQuery({
    queryKey: juryKeys.history(competitionId, codeSubmissionId ?? ""),
    queryFn: () => juryApi.history(competitionId, codeSubmissionId!),
    enabled: Boolean(competitionId) && Boolean(codeSubmissionId),
    refetchInterval: JURY_POLL_MS,
  });
}

function useJuryMutation<TInput, TOutput>(
  competitionId: string,
  fn: (input: TInput) => Promise<TOutput>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: juryKeys.all(competitionId) }),
  });
}

export function useRejudge(competitionId: string) {
  return useJuryMutation(competitionId, (judgingId: string) => juryApi.rejudge(competitionId, judgingId));
}

export function useRejudgeProblem(competitionId: string) {
  return useJuryMutation(
    competitionId,
    ({ challengeId, only }: { challengeId: string; only: RejudgeScope }) =>
      juryApi.rejudgeProblem(competitionId, challengeId, only),
  );
}

export function useOverrideVerdict(competitionId: string) {
  return useJuryMutation(
    competitionId,
    ({ judgingId, verdict, reason }: { judgingId: string; verdict: string; reason: string }) =>
      juryApi.override(competitionId, judgingId, verdict, reason),
  );
}

/** A judging's source, for reading it (staff, or the submitter). */
export function useJudgingSource(competitionId: string, judgingId: string | null) {
  return useQuery({
    queryKey: ["judge", "source", competitionId, judgingId ?? ""] as const,
    queryFn: () => judgingsApi.source(competitionId, judgingId!),
    enabled: Boolean(competitionId) && Boolean(judgingId),
    staleTime: Infinity, // a submission's code never changes
  });
}
