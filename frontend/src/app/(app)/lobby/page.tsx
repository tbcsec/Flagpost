"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { SectionHeader } from "@/components/app/section-header";
import { RulesAcceptModal } from "@/components/competitions/rules-accept-modal";
import { JoinFieldsDialog } from "@/components/registration/join-fields-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  useCompetitions,
  useJoinByCode,
  useJoinCompetition,
} from "@/lib/hooks/use-competitions";
import { GUIDE_PDFS } from "@/lib/guides";
import { useAcceptRules, useFetchRules } from "@/lib/hooks/use-rules";
import { rulesGateRejection, rulesPromptMode } from "@/lib/rules-prompt";
import type { RegistrationValues, RichTextDoc } from "@/lib/types";
import { toast } from "@/stores/toast";

// A pending rules prompt (#57) in front of a join. Acceptance is recorded
// either through the accept endpoint (public join — the competition is
// visible, so its id is known) or by retrying the code join with
// accept_rules=true (private competitions stay undisclosed pre-code).
type RulesPrompt = {
  mode: "accept" | "display";
  rules: RichTextDoc | null;
  acceptVia: { kind: "api"; competitionId: string } | { kind: "join" };
  proceed: () => void;
};

// Lobby — where a competitor who isn't in any competition lands. Joining is now
// fully wired: self-serve for public competitions (the list below) and by
// invite code for private ones. On success the shell's nav switches out of the
// lobby (permissions are refetched) and the joined competition becomes active.
export default function LobbyPage() {
  const t = useTranslations("lobby");
  const tc = useTranslations("common");
  const router = useRouter();
  const { data: competitions } = useCompetitions();
  const join = useJoinCompetition();
  const joinByCode = useJoinByCode();
  const fetchRules = useFetchRules();
  const acceptRules = useAcceptRules();
  const [code, setCode] = useState("");
  const [prompt, setPrompt] = useState<RulesPrompt | null>(null);
  // A public competition selected for join — collect its custom fields (#350)
  // before running the rules-gate + join flow.
  const [joining, setJoining] = useState<{ id: string; name: string } | null>(
    null,
  );

  // Public and not archived — an archived competition is closed to new joiners.
  const publicComps = (competitions ?? []).filter(
    (c) => c.visibility === "public" && !c.archived_at,
  );

  function onJoined(name: string) {
    toast(t("joined", { name }), { variant: "success" });
    router.push("/");
  }

  function joinError(err: unknown) {
    // The email-verification gate (#74) is a 403 with a fixed message — route
    // to the profile page (verify banner + resend button) instead of a
    // dead-end toast. Duck-typed (status/message) rather than an ApiError
    // import — components reach the API only through hooks (ARCHITECTURE.md §8).
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
  }

  function onJoinByCode(e: React.FormEvent) {
    e.preventDefault();
    fireCodeJoin(false);
  }

  function fireCodeJoin(withAcceptance: boolean) {
    joinByCode.mutate(
      { inviteCode: code, acceptRules: withAcceptance },
      {
        onSuccess: async (comp) => {
          setCode("");
          setPrompt(null);
          toast(t("joined", { name: comp.name }), { variant: "success" });
          // Display-only rules can't be shown pre-join on the code path (the
          // competition is undisclosed until the code resolves) — show them
          // now, and move on after Continue.
          const state = await fetchRules(comp.id).catch(() => null);
          if (state && rulesPromptMode(state) === "display") {
            setPrompt({
              mode: "display",
              rules: state.rules,
              acceptVia: { kind: "api", competitionId: comp.id },
              proceed: () => router.push("/"),
            });
          } else {
            router.push("/");
          }
        },
        onError: (err) => {
          const gate = rulesGateRejection(err);
          if (gate) {
            // Mandatory rules: prompt, then retry the join carrying acceptance.
            setPrompt({
              mode: "accept",
              rules: gate.rules,
              acceptVia: { kind: "join" },
              proceed: () => fireCodeJoin(true),
            });
          } else {
            joinError(err);
          }
        },
      },
    );
  }

  async function onPublicJoin(
    compId: string,
    name: string,
    fieldValues: RegistrationValues = {},
  ) {
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
      setPrompt({
        mode,
        rules: state!.rules,
        acceptVia: { kind: "api", competitionId: compId },
        proceed: fire,
      });
    } else {
      fire();
    }
  }

  function onPromptConfirm() {
    if (!prompt) return;
    if (prompt.mode === "display") {
      setPrompt(null);
      prompt.proceed();
    } else if (prompt.acceptVia.kind === "api") {
      acceptRules.mutate(prompt.acceptVia.competitionId, {
        onSuccess: () => {
          setPrompt(null);
          prompt.proceed();
        },
        onError: joinError,
      });
    } else {
      // Acceptance travels with the retried code join; success closes the prompt.
      prompt.proceed();
    }
  }

  return (
    <>
      <SectionHeader
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          // First-visit orientation: the bundled Competitor guide.
          <Button variant="ghost" asChild>
            <a href={GUIDE_PDFS.competitor} target="_blank" rel="noreferrer">
              {t("readGuide")}
            </a>
          </Button>
        }
      />

      {prompt && (
        <RulesAcceptModal
          open
          mode={prompt.mode}
          rules={prompt.rules}
          pending={acceptRules.isPending || joinByCode.isPending || join.isPending}
          onConfirm={onPromptConfirm}
          onCancel={() => setPrompt(null)}
        />
      )}

      <Card>
        <CardHeader>
          <CardTitle>{t("inviteTitle")}</CardTitle>
          <CardDescription>{t("inviteDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex max-w-md gap-3" onSubmit={onJoinByCode}>
            <Input
              placeholder={t("invitePlaceholder")}
              className="font-mono"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
            />
            <Button type="submit" disabled={joinByCode.isPending}>
              {joinByCode.isPending ? t("joining") : t("join")}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("publicTitle")}</CardTitle>
          <CardDescription>{t("publicDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3">
            {publicComps.map((c) => (
              <div
                key={c.id}
                className="flex items-center justify-between gap-3 rounded-md border border-border p-3.5"
              >
                <div>
                  <div className="text-sm font-medium">{c.name}</div>
                  <div className="text-xs capitalize text-muted-foreground">
                    {tc(`competitionMode.${c.participation_mode}`)} ·{" "}
                    {tc(`visibility.${c.visibility}`)}
                  </div>
                </div>
                <Button
                  size="sm"
                  disabled={join.isPending}
                  onClick={() => setJoining({ id: c.id, name: c.name })}
                >
                  {t("join")}
                </Button>
              </div>
            ))}
            {publicComps.length === 0 && (
              <p className="text-sm text-muted-foreground">{t("empty")}</p>
            )}
          </div>
        </CardContent>
      </Card>

      {joining && (
        <JoinFieldsDialog
          competitionId={joining.id}
          competitionName={joining.name}
          onCancel={() => setJoining(null)}
          onSubmit={(fieldValues: RegistrationValues) => {
            const target = joining;
            setJoining(null);
            void onPublicJoin(target.id, target.name, fieldValues);
          }}
        />
      )}
    </>
  );
}
