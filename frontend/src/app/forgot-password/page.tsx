"use client";

import Link from "next/link";
import { useState } from "react";

import { PoweredByFooter } from "@/components/app/powered-by-footer";
import { Lockup } from "@/components/brand/flagpost-mark";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FALLBACK_SETTINGS, useSiteSettings } from "@/lib/hooks/use-site-settings";
import { useForgotPassword } from "@/lib/hooks/use-users";

export default function ForgotPasswordPage() {
  const { data: settings } = useSiteSettings();
  const brand = settings ?? FALLBACK_SETTINGS;
  const forgot = useForgotPassword();
  const [email, setEmail] = useState("");

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    forgot.mutate({ email });
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-6 px-4 py-8">
      <Lockup
        size={40}
        label={brand.platform_name}
        logoUrl={brand.logo_url}
        showWordmark={brand.show_wordmark}
      />
      <Card>
        <CardHeader>
          <CardTitle>Reset your password</CardTitle>
          <CardDescription>
            Enter your account email and we&apos;ll send a reset link.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {forgot.isSuccess ? (
            <p className="text-sm text-muted-foreground">
              If an account exists for <span className="font-medium">{email}</span>,
              a reset link is on its way. Check your inbox (and spam).
            </p>
          ) : (
            <form onSubmit={onSubmit} className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
              <Button type="submit" disabled={forgot.isPending}>
                {forgot.isPending ? "Sending…" : "Send reset link"}
              </Button>
            </form>
          )}
          <p className="mt-4 text-sm text-muted-foreground">
            <Link href="/login" className="text-primary underline">
              Back to sign in
            </Link>
          </p>
        </CardContent>
      </Card>
      <PoweredByFooter />
    </main>
  );
}
