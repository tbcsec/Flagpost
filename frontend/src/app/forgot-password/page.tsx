"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FALLBACK_SETTINGS, useSiteSettings } from "@/lib/hooks/use-site-settings";
import { useForgotPassword } from "@/lib/hooks/use-users";

export default function ForgotPasswordPage() {
  const t = useTranslations("auth.forgotPassword");
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
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </CardHeader>
        <CardContent>
          {forgot.isSuccess ? (
            <p className="text-sm text-muted-foreground">
              {t.rich("success", {
                email,
                b: (chunks) => <span className="font-medium">{chunks}</span>,
              })}
            </p>
          ) : (
            <form onSubmit={onSubmit} className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="email">{t("email")}</Label>
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
              <Button type="submit" disabled={forgot.isPending}>
                {forgot.isPending ? t("submitting") : t("submit")}
              </Button>
            </form>
          )}
          <p className="mt-4 text-sm text-muted-foreground">
            <Link href="/login" className="text-primary underline">
              {t("backToSignIn")}
            </Link>
          </p>
        </CardContent>
      </Card>
      <LocaleSwitcher className="mx-auto" />
      <PoweredByFooter />
    </main>
  );
}
