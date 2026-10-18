"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { RulesAcceptModal } from "@/components/competitions/rules-accept-modal";
import { JoinFieldsDialog } from "@/components/registration/join-fields-dialog";
import { useJoinCompetition } from "@/lib/hooks/use-competitions";
import { useAcceptRules, useFetchRules } from "@/lib/hooks/use-rules";
import { rulesPromptMode } from "@/lib/rules-prompt";
import type { RegistrationValues, RichTextDoc } from "@/lib/types";
import { toast } from "@/stores/toast";

// Self-serve joining of a public competition, shared by the lobby and the join
// panel a non-member sees on a competition picked from the switcher (#478):
// collect its registration fields (#350), show its rules (#57) — accepting them
// through the API, since the competition is visible — then join. On success the
// joined competition becomes active and permissions refetch (useOnJoined).

/** The email-verification gate (#74) is a 403 with a fixed message: route to
 *  the Profile page (verify banner + resend) instead of a dead-end toast.
 *  Duck-typed (status/message) rather than an ApiError import — components
 *  reach the API only through hooks (ARCHITECTURE.md §8). */
export function useJoinErrorHandler() {
  const t = useTranslations("lobby");
  const router = useRouter();
  return (err: unknown) => {
    const e = err as { status?: unknown; message?: unknown };
    if (e.status === 403 && typeof e.message === "string" && e.message.includes("Verify your email")) {
      toast(t("cantJoin"), {
        description: t("verifyEmailHint", { message: e.message }),
        variant: "destructive",
      });
      router.push("/profile");
      return;
    }
    toast(t("cantJoin"), {
      description: (err as Error).message,
      variant: "destructive",
    });
  };
}

type Prompt = {
  mode: "accept" | "display";
  rules: RichTextDoc | null;
  competitionId: string;
  proceed: () => void;
};

export function usePublicJoin({ onJoined }: { onJoined: (name: string) => void }) {
  const join = useJoinCompetition();
  const fetchRules = useFetchRules();
  const acceptRules = useAcceptRules();
  const joinError = useJoinErrorHandler();
  const [joining, setJoining] = useState<{ id: string; name: string } | null>(null);
  const [prompt, setPrompt] = useState<Prompt | null>(null);

  async function joinWith(compId: string, name: string, fieldValues: RegistrationValues) {
    const fire = () =>
      join.mutate(
        { id: compId, fieldValues },
        {
          onSuccess: () => {
            setPrompt(null);
            onJoined(name);
          },
          onError: joinError,
        },
      );
    // Pre-check the rules so the prompt appears before the join attempt; if
    // the check itself fails, fire anyway — the server gate still protects.
    const state = await fetchRules(compId).catch(() => null);
    const mode = state ? rulesPromptMode(state) : null;
    if (mode) {
      setPrompt({ mode, rules: state!.rules, competitionId: compId, proceed: fire });
    } else {
      fire();
    }
  }

  function onPromptConfirm() {
    if (!prompt) return;
    if (prompt.mode === "display") {
      setPrompt(null);
      prompt.proceed();
      return;
    }
    acceptRules.mutate(prompt.competitionId, {
      onSuccess: () => {
        setPrompt(null);
        prompt.proceed();
      },
      onError: joinError,
    });
  }

  const dialogs = (
    <>
      {prompt && (
        <RulesAcceptModal
          open
          mode={prompt.mode}
          rules={prompt.rules}
          pending={acceptRules.isPending || join.isPending}
          onConfirm={onPromptConfirm}
          onCancel={() => setPrompt(null)}
        />
      )}
      {joining && (
        <JoinFieldsDialog
          competitionId={joining.id}
          competitionName={joining.name}
          onCancel={() => setJoining(null)}
          onSubmit={(fieldValues: RegistrationValues) => {
            const target = joining;
            setJoining(null);
            void joinWith(target.id, target.name, fieldValues);
          }}
        />
      )}
    </>
  );

  return {
    /** Begin joining: the fields dialog first (it submits straight through when
     *  the competition has no fields), then rules, then the join itself. */
    start: (id: string, name: string) => setJoining({ id, name }),
    isPending: join.isPending,
    dialogs,
  };
}
