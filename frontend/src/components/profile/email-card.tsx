"use client";

// Self-service add / change / clear of your own email (#106). Before this, an
// account registered without an address (legitimate under ADR-0015) was
// stranded: no password reset, and no way past the #74 verification gate
// without an administrator editing the record by hand.

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSiteSettings } from "@/lib/hooks/use-site-settings";
import { useChangeEmail } from "@/lib/hooks/use-users";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";

export function EmailCard() {
  const user = useAuthStore((s) => s.user);
  const { data: settings } = useSiteSettings();
  const changeEmail = useChangeEmail();
  const confirm = useConfirm();

  const [email, setEmail] = useState(user?.email ?? "");
  const [password, setPassword] = useState("");

  const current = user?.email ?? null;
  const verificationRequired = !!settings?.email_verification_enabled;
  // Removing the address is refused server-side while a verification gate is
  // on — an account would have no way to satisfy it.
  const canClear = !!current && !verificationRequired;
  const changed = email.trim().toLowerCase() !== (current ?? "").toLowerCase();

  function submit(newEmail: string | null, successMessage: string) {
    changeEmail.mutate(
      { current_password: password, new_email: newEmail },
      {
        onSuccess: (updated) => {
          setPassword("");
          setEmail(updated.email ?? "");
          toast(
            updated.email && verificationRequired
              ? `${successMessage} — check your inbox to verify it`
              : successMessage,
            { variant: "success" },
          );
        },
      },
    );
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    submit(email.trim(), current ? "Email updated" : "Email added");
  }

  async function onClear() {
    if (
      !(await confirm({
        title: "Remove your email address?",
        description:
          "You'll lose access to password reset, and an administrator will have to set an address for you to get it back.",
        confirmLabel: "Remove",
        destructive: true,
      }))
    ) {
      return;
    }
    submit(null, "Email removed");
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Email</CardTitle>
        <CardDescription>
          {current
            ? "Used for password resets and account notices."
            : "No email set — add one to enable password reset."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="grid max-w-md gap-4">
          <div className="grid gap-2">
            <Label htmlFor="pem">Email address</Label>
            <Input
              id="pem"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
              autoComplete="email"
            />
            {current && changed && (
              <p className="text-xs text-muted-foreground">
                {verificationRequired
                  ? "Changing this will require verifying the new address before you can join a competition."
                  : "We'll let your current address know it was changed."}
              </p>
            )}
          </div>

          <div className="grid gap-2">
            <Label htmlFor="pemcur">Current password</Label>
            <Input
              id="pemcur"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <p className="text-xs text-muted-foreground">
              Confirming your password keeps someone with access to an open
              session from repointing where password resets are sent.
            </p>
          </div>

          {changeEmail.isError && (
            <p role="alert" className="text-sm text-destructive">
              {(changeEmail.error as Error).message}
            </p>
          )}

          <div className="flex items-center gap-2">
            <Button type="submit" disabled={changeEmail.isPending || !changed}>
              {changeEmail.isPending ? "Saving…" : current ? "Update email" : "Add email"}
            </Button>
            {canClear && (
              <Button
                type="button"
                variant="ghost"
                className="text-destructive"
                disabled={changeEmail.isPending || !password}
                onClick={onClear}
              >
                Remove
              </Button>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
