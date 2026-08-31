"use client";

import { Suspense, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { SectionHeader } from "@/components/app/section-header";
import { AvatarCard } from "@/components/profile/avatar-card";
import { UsernameCard } from "@/components/profile/username-card";
import { MyCertificatesCard } from "@/components/profile/certificates-card";
import { MyApiTokensCard } from "@/components/profile/api-tokens-card";
import { EmailCard } from "@/components/profile/email-card";
import { NotificationPreferencesCard } from "@/components/profile/notification-preferences";
import { RegistrationDetailsCard } from "@/components/registration/registration-details-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useSiteSettings } from "@/lib/hooks/use-site-settings";
import { useChangePassword, useResendVerification } from "@/lib/hooks/use-users";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";

// Profile, grouped into tabs (#113) the way Admin → Site settings is (#104): the
// page has grown past a single scroll — password, email, notification prefs and
// personal API tokens. Account (credentials + email) · Notifications · API tokens.
//
// Panels stay **mounted** and are toggled with `hidden`, following the settings
// precedent: a half-typed password or an in-progress email edit survives a look
// at another tab. The display name is still read-only — renaming has no endpoint
// yet, and it's the primary login identifier (ADR-0015).
type Tab = "account" | "notifications" | "tokens" | "certificates";

// Labels resolve through `t("tabs.<value>")` at render (the module-level array
// can't call the hook) — the value doubles as the message key.
const TAB_VALUES: Tab[] = ["account", "notifications", "tokens", "certificates"];

/** The tab named in `?tab=`, or the first one for a stale/absent value. */
function resolveTab(requested: string | null): Tab {
  return TAB_VALUES.find((t) => t === requested) ?? TAB_VALUES[0];
}

// Email verification (#74): shown only when the site requires it and this
// account hasn't confirmed its address yet. An email-less account is pointed at
// the Email card rather than offered a resend button with nothing to send to —
// since #106 that's a self-service fix, not an admin request.
function VerifyEmailBanner({ user }: { user: { email: string | null } }) {
  const t = useTranslations("profile.verify");
  const resend = useResendVerification();
  return (
    <Card className="border-warning/50">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {user.email ? (
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="outline"
              disabled={resend.isPending || resend.isSuccess}
              onClick={() =>
                resend.mutate(undefined, {
                  onSuccess: () => toast(t("sentToast"), { variant: "success" }),
                  onError: (err) =>
                    toast(t("sendError"), {
                      description: (err as Error).message,
                      variant: "destructive",
                    }),
                })
              }
            >
              {resend.isPending
                ? t("sending")
                : resend.isSuccess
                  ? t("sent")
                  : t("resend")}
            </Button>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {t.rich("noEmail", {
              b: (chunks) => (
                <span className="font-medium text-foreground">{chunks}</span>
              ),
            })}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// Password change (POST /api/auth/change-password). Local draft state lives here
// so it survives tab switches — the panel stays mounted.
function PasswordCard() {
  const t = useTranslations("profile.password");
  const user = useAuthStore((s) => s.user);
  const changePassword = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    changePassword.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setCurrent("");
          setNext("");
          toast(t("changedToast"), { variant: "success" });
        },
      },
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="grid max-w-md gap-4">
          <div className="grid gap-2">
            <Label htmlFor="pdn">{t("displayName")}</Label>
            {/* Renaming has no endpoint yet — read-only. Email is its own card
                below, where it's editable (#106). */}
            <Input id="pdn" defaultValue={user?.display_name ?? ""} disabled />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="pcur">{t("current")}</Label>
            <Input
              id="pcur"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              required
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="ppw">{t("new")}</Label>
            <Input
              id="ppw"
              type="password"
              autoComplete="new-password"
              minLength={8}
              value={next}
              onChange={(e) => setNext(e.target.value)}
              required
            />
          </div>
          {changePassword.isError && (
            <p role="alert" className="text-sm text-destructive">{(changePassword.error as Error).message}</p>
          )}
          <div className="flex items-center gap-3">
            <Button type="submit" className="w-fit" disabled={changePassword.isPending}>
              {changePassword.isPending ? t("saving") : t("submit")}
            </Button>
            {changePassword.isSuccess && (
              <span className="text-sm text-muted-foreground">{t("changed")}</span>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function ProfileInner() {
  const t = useTranslations("profile");
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const user = useAuthStore((s) => s.user);
  const { data: settings } = useSiteSettings();
  const { competitionId, data: competition } = useActiveCompetition();
  const needsVerification =
    !!settings?.email_verification_enabled && !!user && !user.email_verified_at;

  const tab = resolveTab(searchParams.get("tab"));

  function setTab(next: Tab) {
    // push, not replace: the URL is the state, so Back undoes a tab switch.
    // scroll:false keeps a long tab from jumping to the top.
    const query = new URLSearchParams(searchParams.toString());
    query.set("tab", next);
    router.push(`${pathname}?${query}`, { scroll: false });
  }

  return (
    <>
      <SectionHeader title={t("title")} subtitle={t("subtitle")} />

      <Tabs
        tabs={TAB_VALUES.map((value) => ({ value, label: t(`tabs.${value}`) }))}
        value={tab}
        onValueChange={(v) => setTab(v as Tab)}
      />

      <div className={tab === "account" ? "grid gap-6" : "hidden"}>
        {needsVerification && <VerifyEmailBanner user={user!} />}
        <AvatarCard />
        <UsernameCard />
        <PasswordCard />
        <EmailCard />
        {/* Custom registration answers for the active individual competition
            (#350) — team answers live in the team panel. */}
        {competitionId && competition?.participation_mode === "individual" && (
          <RegistrationDetailsCard competitionId={competitionId} />
        )}
      </div>

      <div className={tab === "notifications" ? "" : "hidden"}>
        <NotificationPreferencesCard />
      </div>

      <div className={tab === "tokens" ? "" : "hidden"}>
        <MyApiTokensCard />
      </div>

      <div className={tab === "certificates" ? "" : "hidden"}>
        <MyCertificatesCard />
      </div>
    </>
  );
}

/** `useSearchParams` needs a Suspense boundary or Next refuses to prerender the
 *  route — the build fails outright rather than degrading (same as settings). */
export default function ProfilePage() {
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <ProfileInner />
    </Suspense>
  );
}
