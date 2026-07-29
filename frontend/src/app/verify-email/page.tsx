"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef } from "react";

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
import { FALLBACK_SETTINGS, useSiteSettings } from "@/lib/hooks/use-site-settings";
import { useVerifyEmail } from "@/lib/hooks/use-users";

function VerifyForm() {
  const { data: settings } = useSiteSettings();
  const brand = settings ?? FALLBACK_SETTINGS;
  const params = useSearchParams();
  const token = params.get("token") ?? "";
  const verify = useVerifyEmail();
  const attempted = useRef(false);

  useEffect(() => {
    if (!token || attempted.current) return;
    attempted.current = true;
    verify.mutate({ token });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

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
          <CardTitle>Verify your email</CardTitle>
          <CardDescription>Confirming the address on your account.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          {!token ? (
            <p role="alert" className="text-sm text-destructive">
              This link is missing its verification token.
            </p>
          ) : verify.isPending || verify.isIdle ? (
            <p className="text-sm text-muted-foreground">Verifying…</p>
          ) : verify.isSuccess ? (
            <p className="text-sm text-success">
              Your email is verified. You can now join competitions.
            </p>
          ) : (
            <p role="alert" className="text-sm text-destructive">
              {(verify.error as Error)?.message ??
                "This verification link is invalid or has expired."}
            </p>
          )}
          <Button asChild className="w-fit">
            <Link href="/login">Continue to sign in</Link>
          </Button>
        </CardContent>
      </Card>
      <PoweredByFooter />
    </main>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={null}>
      <VerifyForm />
    </Suspense>
  );
}
