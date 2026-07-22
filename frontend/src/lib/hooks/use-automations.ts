"use client";

// One hook module per domain (ARCHITECTURE.md §8). Automation rules (§5) —
// anticipated by §8's own example list. Phase 1 scope: list/toggle/delete for
// the minimal rules surface; the visual builder (§5.5) arrives in Phase 3 and
// extends this module rather than replacing it.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { automationsApi } from "@/lib/api";
import type { AutomationRule, AutomationRuleInput } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

const automationKeys = {
  all: ["automations"] as const,
  list: (competitionId?: string) =>
    ["automations", "list", competitionId ?? "global"] as const,
  catalog: ["automations", "catalog"] as const,
  personal: ["automations", "personal"] as const,
};

/** Org rules visible in a competition's context (its own + the globals that
 *  fire there), or the global-only surface when no competition is given. */
export function useAutomations(competitionId?: string, enabled = true) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: automationKeys.list(competitionId),
    queryFn: () => automationsApi.list(competitionId),
    enabled: enabled && isAuthenticated,
  });
}

/** The builder catalog. The **trigger** list is permission-filtered per
 *  competition context (§5.1), so pass the competition whose rules are being
 *  edited; omit it for the global (admin) surface. */
export function useAutomationCatalog(competitionId?: string) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: [...automationKeys.catalog, competitionId ?? "global"],
    queryFn: () => automationsApi.catalog(competitionId),
    enabled: isAuthenticated,
    staleTime: 5 * 60_000, // only changes with a deploy or a role change
  });
}

function useInvalidate() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: automationKeys.all });
}

export function useCreateAutomation(competitionId?: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (input: AutomationRuleInput) =>
      automationsApi.create(input, competitionId),
    onSuccess: invalidate,
  });
}

export function useUpdateAutomation() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ ruleId, input }: { ruleId: string; input: AutomationRuleInput }) =>
      automationsApi.update(ruleId, input),
    onSuccess: invalidate,
  });
}

export function useDeleteAutomation() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (ruleId: string) => automationsApi.remove(ruleId),
    onSuccess: invalidate,
  });
}

/** Full-rule PUT with just the enabled bit flipped — the toggle the list
 *  renders. Kept here so the page never assembles a rule body itself. */
export function useToggleAutomation() {
  const update = useUpdateAutomation();
  return {
    ...update,
    toggle: (rule: AutomationRule) =>
      update.mutate({
        ruleId: rule.id,
        input: {
          name: rule.name,
          trigger_type: rule.trigger_type,
          conditions: rule.conditions,
          actions: rule.actions,
          is_enabled: !rule.is_enabled,
        },
      }),
  };
}

// --- personal rules (§5.1): notify-self, no automation permission needed -----

type PersonalInput = AutomationRuleInput & { competition_id?: string | null };

export function usePersonalAutomations() {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: automationKeys.personal,
    queryFn: () => automationsApi.personal.list(),
    enabled: isAuthenticated,
  });
}

export function useCreatePersonalAutomation() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (input: PersonalInput) => automationsApi.personal.create(input),
    onSuccess: invalidate,
  });
}

export function useUpdatePersonalAutomation() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ ruleId, input }: { ruleId: string; input: PersonalInput }) =>
      automationsApi.personal.update(ruleId, input),
    onSuccess: invalidate,
  });
}

export function useDeletePersonalAutomation() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (ruleId: string) => automationsApi.personal.remove(ruleId),
    onSuccess: invalidate,
  });
}
