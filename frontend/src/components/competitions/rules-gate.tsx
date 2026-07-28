"use client";

import { RulesAcceptModal } from "@/components/competitions/rules-accept-modal";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useAcceptRules, useCompetitionRules } from "@/lib/hooks/use-rules";
import { toast } from "@/stores/toast";

// In-app re-acceptance gate (#57): when a member's acceptance is missing for
// the active competition — typically because staff added/changed the rules
// override, which resets acceptances — a blocking prompt appears until they
// accept. The server computes `required` (mandatory + unaccepted + member +
// not staff-exempt), so a non-member browsing a public competition is never
// nagged, and display-only rules never block anyone.
export function RulesGate() {
  const { competitionId } = useActiveCompetition();
  const rules = useCompetitionRules(competitionId ?? "");
  const accept = useAcceptRules();

  if (!competitionId || !rules.data?.required) return null;

  return (
    <RulesAcceptModal
      open
      mode="accept"
      rules={rules.data.rules}
      dismissable={false}
      pending={accept.isPending}
      onConfirm={() =>
        accept.mutate(competitionId, {
          onSuccess: () => toast("Rules accepted", { variant: "success" }),
          onError: (err) =>
            toast("Couldn't record acceptance", {
              description: (err as Error).message,
              variant: "destructive",
            }),
        })
      }
    />
  );
}
