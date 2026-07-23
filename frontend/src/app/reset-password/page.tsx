"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

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
import { useResetPassword } from "@/lib/hooks/use-users";
import { toast } from "@/stores/toast";

function ResetForm() {
  const { data: settings } = useSiteSettings();
  const brand = settings ?? FALLBACK_SETTINGS;
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("token") ?? "";
  const reset = useResetPassword();
  const [password, setPassword] = useState("");

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    reset.mutate(
      { token, new_password: password },
      {
        onSuccess: () => {
          toast("Password reset — please sign in", { variant: "success" });
          router.push("/login");
        },
      },
    );
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
          <CardTitle>Choose a new password</CardTitle>
          <CardDescription>Enter a new password for your account.</CardDescription>
        </CardHeader>
        <CardContent>
          {!token ? (
            <p className="text-sm text-destructive">
              This link is missing its reset token. Request a new one from{" "}
              <Link href="/forgot-password" className="underline">
                forgot password
              </Link>
              .
            </p>
          ) : (
            <form onSubmit={onSubmit} className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="new-password">New password</Label>
                <Input
                  id="new-password"
                  type="password"
                  autoComplete="new-password"
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>
              {reset.isError && (
                <p className="text-sm text-destructive">{(reset.error as Error).message}</p>
              )}
              <Button type="submit" disabled={reset.isPending}>
                {reset.isPending ? "Saving…" : "Set new password"}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
      <PoweredByFooter />
    </main>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetForm />
    </Suspense>
  );
}
