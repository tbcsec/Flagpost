"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { SectionHeader } from "@/components/app/section-header";
import { RulesAcceptModal } from "@/components/competitions/rules-accept-modal";
import {
  useJoinErrorHandler,
  usePublicJoin,
} from "@/components/competitions/use-public-join";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useCompetitions, useJoinByCode } from "@/lib/hooks/use-competitions";
import { GUIDE_PDFS } from "@/lib/guides";
import { useAccess } from "@/lib/hooks/use-permissions";
import { useAcceptRules, useFetchRules } from "@/lib/hooks/use-rules";
import { rulesGateRejection, rulesPromptMode } from "@/lib/rules-prompt";
import type { RichTextDoc } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";

// A pending rules prompt (#57) in front of an invite-code join. Acceptance is
// recorded either through the accept endpoint (rules shown after the join) or
// by retrying the code join with accept_rules=true (private competitions stay
// undisclosed pre-code). Public joins run their own prompt (usePublicJoin).
type RulesPrompt = {
  mode: "accept" | "display";
  rules: RichTextDoc | null;
  acceptVia: { kind: "api"; competitionId: string } | { kind: "join" };
  proceed: () => void;
};

// Lobby — where a competitor who isn't in any competition lands, and where
// anyone comes back to join another (the switcher's "Join a competition",
// #478). Self-serve for public competitions (the list below) and by invite
// code for private ones. On success the shell's nav switches out of the lobby
// (permissions are refetched) and the joined competition becomes active.
export default function LobbyPage() {
  const t = useTranslations("lobby");
  const tc = useTranslations("common");
  const router = useRouter();
  const { data: competitions } = useCompetitions();
  const access = useAccess();
  const setActiveCompetition = useAuthStore((s) => s.setActiveCompetition);
  const joinByCode = useJoinByCode();
  const fetchRules = useFetchRules();
  const acceptRules = useAcceptRules();
  const joinError = useJoinErrorHandler();
  const [code, setCode] = useState("");
  const [prompt, setPrompt] = useState<RulesPrompt | null>(null);
  const publicJoin = usePublicJoin({ onJoined });

  // Public and not archived — an archived competition is closed to new joiners.
  const publicComps = (competitions ?? []).filter(
    (c) => c.visibility === "public" && !c.archived_at,
  );

  function onJoined(name: string) {
    toast(t("joined", { name }), { variant: "success" });
    router.push("/");
  }

  function openCompetition(id: string) {
    setActiveCompetition(id);
    router.push("/");
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
        subtitle={access.inLobby ? t("subtitle") : t("subtitleMember")}
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
          pending={acceptRules.isPending || joinByCode.isPending}
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
                {access.isMemberOf(c.id) ? (
                  <div className="flex items-center gap-2">
                    <Badge variant="muted">{t("joinedBadge")}</Badge>
                    <Button size="sm" variant="outline" onClick={() => openCompetition(c.id)}>
                      {t("open")}
                    </Button>
                  </div>
                ) : (
                  <Button
                    size="sm"
                    disabled={publicJoin.isPending}
                    onClick={() => publicJoin.start(c.id, c.name)}
                  >
                    {t("join")}
                  </Button>
                )}
              </div>
            ))}
            {publicComps.length === 0 && (
              <p className="text-sm text-muted-foreground">{t("empty")}</p>
            )}
          </div>
        </CardContent>
      </Card>

      {publicJoin.dialogs}
    </>
  );
}
