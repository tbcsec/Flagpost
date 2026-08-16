"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
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
import { useRegister } from "@/lib/hooks/use-users";

export default function RegisterPage() {
  const t = useTranslations("auth.register");
  const router = useRouter();
  const register = useRegister();
  const { data: settings } = useSiteSettings();
  const brand = settings ?? FALLBACK_SETTINGS;
  const platformName = brand.platform_name;
  const registrationOpen = brand.registration_open;
  const emailRequired = brand.email_required;
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    register.mutate(
      // Email is optional — omit it when blank rather than sending "".
      { display_name: displayName, password, email: email.trim() || undefined },
      { onSuccess: () => router.push("/") },
    );
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 p-8">
      <div className="flex justify-center">
        <Lockup
          size={40}
          theme="dark"
          label={platformName}
          logoUrl={brand.logo_url}
          showWordmark={brand.show_wordmark}
        />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </CardHeader>
        <CardContent>
          {!registrationOpen ? (
            <p className="text-sm text-muted-foreground">{t("closed")}</p>
          ) : (
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="display_name">{t("username")}</Label>
              <Input
                id="display_name"
                autoComplete="username"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                required
              />
              <p className="text-xs text-muted-foreground">{t("usernameHint")}</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">
                {emailRequired ? t("email") : t("emailOptional")}
              </Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required={emailRequired}
              />
              <p className="text-xs text-muted-foreground">
                {emailRequired ? t("emailHintRequired") : t("emailHintOptional")}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">{t("password")}</Label>
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {register.isError && (
              <p role="alert" className="text-sm text-destructive">
                {(register.error as Error).message}
              </p>
            )}
            <Button
              type="submit"
              className="w-full"
              disabled={register.isPending}
            >
              {register.isPending ? t("submitting") : t("submit")}
            </Button>
          </form>
          )}
          <p className="mt-4 text-sm text-muted-foreground">
            {t("haveAccount")}{" "}
            <Link href="/login" className="text-primary hover:underline">
              {t("signIn")}
            </Link>
          </p>
        </CardContent>
      </Card>
      <LocaleSwitcher className="mx-auto" />
      <PoweredByFooter />
    </main>
  );
}
