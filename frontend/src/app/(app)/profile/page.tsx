"use client";

import { useState } from "react";

import { SectionHeader } from "@/components/app/section-header";
import { NotificationPreferencesCard } from "@/components/profile/notification-preferences";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSiteSettings } from "@/lib/hooks/use-site-settings";
import { useChangePassword, useResendVerification } from "@/lib/hooks/use-users";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";

// Email verification (#74): shown only when the site requires it and this
// account hasn't confirmed its address yet. There's no self-service
// add/change-email flow (a separate issue) — an email-less account is told to
// contact an administrator rather than offered a dead-end resend button.
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
            Your account has no email address on file. Contact an administrator to have one added.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// Profile. Changing your password IS wired (POST /api/auth/change-password).
// Editing display name / email needs a user-update endpoint that doesn't exist
// yet — shown read-only. Notification preferences are wired (§4.4).
export default function ProfilePage() {
  const user = useAuthStore((s) => s.user);
  const { data: settings } = useSiteSettings();
  const changePassword = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const needsVerification =
    !!settings?.email_verification_enabled && !!user && !user.email_verified_at;

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
    <>
      <SectionHeader title="Profile" subtitle="Your account and notification preferences" />

      {needsVerification && <VerifyEmailBanner user={user!} />}

      <Card>
        <CardHeader>
          <CardTitle>Account</CardTitle>
          <CardDescription>Change your password</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="grid max-w-md gap-4">
            <div className="grid gap-2">
              <Label htmlFor="pdn">Display name</Label>
              {/* Editing name/email has no endpoint yet — shown read-only. */}
              <Input id="pdn" defaultValue={user?.display_name ?? ""} disabled />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="pem">Email (optional)</Label>
              <Input
                id="pem"
                type="email"
                defaultValue={user?.email ?? ""}
                placeholder="No email set"
                disabled
              />
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

      <NotificationPreferencesCard />
    </>
  );
}
