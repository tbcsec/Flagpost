"use client";

// The invite-link landing (#427 Phase 3) — what a recipient sees when they open
// a shared /invite/{token} URL. Lives OUTSIDE the (app) shell, like /login and
// /public/[competitionId]: a logged-out visitor must be able to land here.
//
// Resolve is anonymous; what happens next depends on the link's capability:
// - join: sign in / register (carrying this path as the validated ?next= so the
//   token survives the auth round-trip — including SSO via return_to), then a
//   one-click join through the same gates as every other join path. A mandatory
//   rules 403 is retried with acceptance via the shared RulesAcceptModal, the
//   invite-code flow's exact contract (#57).
// - view: a hand-off to the public spectator board (the link resolves only
//   while that surface is available — the server fails closed).

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { LocaleSwitcher } from "@/components/app/locale-switcher";
import { PoweredByFooter } from "@/components/app/powered-by-footer";
import { Lockup } from "@/components/brand/flagpost-mark";
import { RulesAcceptModal } from "@/components/competitions/rules-accept-modal";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useInviteLinkResolve, useJoinViaInviteLink } from "@/lib/hooks/use-invite-links";
import { useBrandSettings } from "@/lib/hooks/use-site-settings";
import { rulesGateRejection } from "@/lib/rules-prompt";
import type { RichTextDoc } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";

export default function InviteLandingPage() {
  const t = useTranslations("inviteLinks.landing");
  const router = useRouter();
  const { token } = useParams<{ token: string }>();
  const resolve = useInviteLinkResolve(token);
  const join = useJoinViaInviteLink(token);
  const authStatus = useAuthStore((s) => s.status);
  const brand = useBrandSettings();
  const [rulesPrompt, setRulesPrompt] = useState<RichTextDoc | null>(null);
  const [joinError, setJoinError] = useState<string | null>(null);

  const data = resolve.data;
  const nextPath = `/invite/${token}`;

  function fireJoin(withAcceptance: boolean) {
    setJoinError(null);
    join.mutate(
      { accept_rules: withAcceptance },
      {
        onSuccess: (competition) => {
          toast(t("joinedToast", { name: competition.name }));
          router.push("/");
        },
        onError: (err) => {
          // Mandatory rules (#57): the 403 carries the document — prompt and
          // retry with acceptance, exactly like the invite-code flow.
          const gate = rulesGateRejection(err);
          if (gate) {
            setRulesPrompt(gate.rules);
            return;
          }
          setJoinError((err as Error).message);
        },
      },
    );
  }

  // The email-verification join gate's message is a stable server constant; the
  // lobby special-cases it the same way to point at the profile page.
  const needsEmailVerify = joinError?.includes("Verify your email") ?? false;

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 p-8">
      <div className="flex justify-center">
        <Lockup
          size={40}
          theme="dark"
          label={brand.platform_name}
          logoUrl={brand.logo_url}
          showWordmark={brand.show_wordmark}
        />
      </div>

      {resolve.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : resolve.isError || !data ? (
        <Card>
          <CardHeader>
            <CardTitle>{t("invalidTitle")}</CardTitle>
            <CardDescription>{t("invalidDescription")}</CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>
              {data.capability === "join"
                ? t("joinTitle", { name: data.competition_name })
                : data.competition_name}
            </CardTitle>
            <CardDescription>
              {data.capability === "view"
                ? t("viewDescription")
                : t(`status.${data.competition_status}`)}
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            {data.capability === "view" ? (
              <Button asChild className="w-full">
                <Link href={`/public/${data.competition_id}`}>
                  {t("viewBoard")}
                </Link>
              </Button>
            ) : !data.actionable ? (
              // Why the link can't admit right now (#427 Phase 4): ended, or
              // the competition's registration window. Honest per-reason copy.
              <p className="text-sm text-muted-foreground">
                {t(`blocked.${data.reason ?? "ended"}`)}
              </p>
            ) : authStatus === "loading" ? (
              <Skeleton className="h-10 w-full" />
            ) : authStatus === "anonymous" ? (
              <>
                <Button asChild className="w-full">
                  <Link href={`/login?next=${encodeURIComponent(nextPath)}`}>
                    {t("signIn")}
                  </Link>
                </Button>
                {brand.registration_open && (
                  <Button asChild variant="outline" className="w-full">
                    <Link href={`/register?next=${encodeURIComponent(nextPath)}`}>
                      {t("register")}
                    </Link>
                  </Button>
                )}
              </>
            ) : (
              <>
                <Button
                  className="w-full"
                  disabled={join.isPending}
                  onClick={() => fireJoin(false)}
                >
                  {join.isPending ? t("joining") : t("join")}
                </Button>
                {joinError && (
                  <div role="alert" className="grid gap-1 text-sm text-destructive">
                    <p>{joinError}</p>
                    {needsEmailVerify && (
                      <Link href="/profile" className="text-primary hover:underline">
                        {t("goToProfile")}
                      </Link>
                    )}
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>
      )}

      <RulesAcceptModal
        open={Boolean(rulesPrompt)}
        mode="accept"
        rules={rulesPrompt}
        pending={join.isPending}
        onConfirm={() => {
          setRulesPrompt(null);
          fireJoin(true);
        }}
        onCancel={() => setRulesPrompt(null)}
      />

      <LocaleSwitcher className="mx-auto" />
      <PoweredByFooter />
    </main>
  );
}
