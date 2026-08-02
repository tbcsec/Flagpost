"use client";

import { Suspense, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { SectionHeader } from "@/components/app/section-header";
import { MyApiTokensCard } from "@/components/profile/api-tokens-card";
import { EmailCard } from "@/components/profile/email-card";
import { NotificationPreferencesCard } from "@/components/profile/notification-preferences";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
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
type Tab = "account" | "notifications" | "tokens";

const TABS: { value: Tab; label: string }[] = [
  { value: "account", label: "Account" },
  { value: "notifications", label: "Notifications" },
  { value: "tokens", label: "API tokens" },
];

/** The tab named in `?tab=`, or the first one for a stale/absent value. */
function resolveTab(requested: string | null): Tab {
  return TABS.find((t) => t.value === requested)?.value ?? TABS[0].value;
}

// Email verification (#74): shown only when the site requires it and this
// account hasn't confirmed its address yet. An email-less account is pointed at
// the Email card rather than offered a resend button with nothing to send to —
// since #106 that's a self-service fix, not an admin request.
function VerifyEmailBanner({ user }: { user: { email: string | null } }) {
  const resend = useResendVerification();
  return (
    <Card className="border-warning/50">
      <CardHeader>
        <CardTitle>Verify your email</CardTitle>
        <CardDescription>
          This instance requires a verified email before you can join a competition.
        </CardDescription>
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
                  onSuccess: () => toast("Verification email sent", { variant: "success" }),
                  onError: (err) =>
                    toast("Couldn't send it", {
                      description: (err as Error).message,
                      variant: "destructive",
                    }),
                })
              }
            >
              {resend.isPending
                ? "Sending…"
                : resend.isSuccess
                  ? "Sent — check your inbox"
                  : "Resend verification email"}
            </Button>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Your account has no email address on file. Add one under{" "}
            <span className="font-medium text-foreground">Email</span> below, and
            we&apos;ll send you a verification link.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// Password change (POST /api/auth/change-password). Local draft state lives here
// so it survives tab switches — the panel stays mounted.
function PasswordCard() {
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
          toast("Password changed", { variant: "success" });
        },
      },
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Account</CardTitle>
        <CardDescription>Change your password</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="grid max-w-md gap-4">
          <div className="grid gap-2">
            <Label htmlFor="pdn">Display name</Label>
            {/* Renaming has no endpoint yet — read-only. Email is its own card
                below, where it's editable (#106). */}
            <Input id="pdn" defaultValue={user?.display_name ?? ""} disabled />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="pcur">Current password</Label>
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
            <Label htmlFor="ppw">New password</Label>
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
              {changePassword.isPending ? "Saving…" : "Change password"}
            </Button>
            {changePassword.isSuccess && (
              <span className="text-sm text-muted-foreground">Password changed.</span>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function ProfileInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const user = useAuthStore((s) => s.user);
  const { data: settings } = useSiteSettings();
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
      <SectionHeader title="Profile" subtitle="Your account and notification preferences" />

      <Tabs tabs={TABS} value={tab} onValueChange={(v) => setTab(v as Tab)} />

      <div className={tab === "account" ? "grid gap-6" : "hidden"}>
        {needsVerification && <VerifyEmailBanner user={user!} />}
        <PasswordCard />
        <EmailCard />
      </div>

      <div className={tab === "notifications" ? "" : "hidden"}>
        <NotificationPreferencesCard />
      </div>

      <div className={tab === "tokens" ? "" : "hidden"}>
        <MyApiTokensCard />
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
