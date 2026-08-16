"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useEffect, useRef } from "react";

import { LocaleSwitcher } from "@/components/app/locale-switcher";
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
  const t = useTranslations("auth.verifyEmail");
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
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          {!token ? (
            <p role="alert" className="text-sm text-destructive">
              {t("missingToken")}
            </p>
          ) : verify.isPending || verify.isIdle ? (
            <p className="text-sm text-muted-foreground">{t("verifying")}</p>
          ) : verify.isSuccess ? (
            <p className="text-sm text-success">{t("success")}</p>
          ) : (
            <p role="alert" className="text-sm text-destructive">
              {(verify.error as Error)?.message ?? t("fallbackError")}
            </p>
          )}
          <Button asChild className="w-fit">
            <Link href="/login">{t("continue")}</Link>
          </Button>
        </CardContent>
      </Card>
      <LocaleSwitcher className="mx-auto" />
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
