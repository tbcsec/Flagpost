"use client";

import { useState } from "react";

import { NotWiredNote, SectionHeader } from "@/components/app/section-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useChangePassword } from "@/lib/hooks/use-users";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";

// Profile. Changing your password IS wired (POST /api/auth/change-password).
// Editing display name / email needs a user-update endpoint that doesn't exist
// yet — the notification inbox itself is live (topbar bell), only per-user
// preferences (mute/channels) remain unbuilt; flagged.
export default function ProfilePage() {
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

  const prefs = [
    "Email me on ticket replies",
    "Email me on new announcements",
    "Email me on solve confirmations",
    "Browser notifications",
  ];

  return (
    <>
      <SectionHeader title="Profile" subtitle="Your account and notification preferences" />

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
              <Label htmlFor="pem">Email</Label>
              <Input id="pem" type="email" defaultValue={user?.email ?? ""} disabled />
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
              <p className="text-sm text-destructive">{(changePassword.error as Error).message}</p>
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

      <Card>
        <CardHeader>
          <CardTitle>Notification preferences</CardTitle>
          <CardDescription>Your personal inbox — separate from broadcast announcements</CardDescription>
        </CardHeader>
        <CardContent>
          <NotWiredNote>The notification inbox is live in the topbar bell; these per-user preferences (mute, delivery channels) aren&apos;t built yet.</NotWiredNote>
          <ul className="mt-4 grid max-w-md gap-3">
            {prefs.map((label, i) => (
              <li key={label} className="flex items-center justify-between gap-3">
                <span className="text-sm">{label}</span>
                <input type="checkbox" defaultChecked={i !== 2} disabled />
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </>
  );
}
