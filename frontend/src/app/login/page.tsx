"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Suspense, useState } from "react";

import { LocaleSwitcher } from "@/components/app/locale-switcher";
import { PoweredByFooter } from "@/components/app/powered-by-footer";
import { Lockup } from "@/components/brand/flagpost-mark";
import { SsoBrandIcon } from "@/components/brand/sso-brand-icons";
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
import dynamic from "next/dynamic";

import { FALLBACK_SETTINGS, useSiteSettings } from "@/lib/hooks/use-site-settings";
import { useAuthProviders, useLogin } from "@/lib/hooks/use-users";

// Loaded on demand, deliberately: the read-only TipTap renderer costs ~126 kB
// of first-load JS, and most installs never configure a notice — every
// visitor's sign-in page must not pay for the feature's mere existence. The
// chunk is only fetched when a notice actually exists (see below).
const RichTextView = dynamic(
  () => import("@/components/ui/rich-text-view").then((m) => m.RichTextView),
  { ssr: false },
);
import { useSearchParams } from "next/navigation";

// The callback redirects here with a short code rather than the provider's own
// message — a failure is usually a misconfiguration whose detail (endpoints,
// client ids, internal hostnames) shouldn't be reflected to a browser. Server
// logs carry the specifics. The messages live under auth.login.ssoErrors; an
// unknown code falls through to "default".
const SSO_ERROR_CODES = [
  "invalid_state",
  "expired",
  "invalid_token",
  "provider_unavailable",
  "provider_denied",
  "invalid_response",
  "account_disabled",
  // #118 — kept generic on purpose: neither reveals whether an account exists.
  "domain_not_allowed",
  "registration_closed",
] as const;
type SsoErrorCode = (typeof SSO_ERROR_CODES)[number] | "default";

// Shown only on a demo instance (seeded by auth/demo.py). Password is "password".
// Labels/descriptions come from auth.login.demo.accounts.<user>.
const DEMO_ACCOUNTS = ["admin", "judge", "participant"] as const;

// Split from the default export purely so useSearchParams (reading the SSO
// `?error=` code) sits inside a Suspense boundary. Without one, Next refuses to
// statically prerender this route — `npm run build` fails rather than degrading,
// so it's a build-time contract, not a runtime nicety.
function LoginForm() {
  const t = useTranslations("auth.login");
  const router = useRouter();
  const login = useLogin();
  const { data: settings } = useSiteSettings();
  const { data: providers } = useAuthProviders();
  const searchParams = useSearchParams();
  const ssoError = searchParams.get("error");
  const ssoErrorKey: SsoErrorCode | null = ssoError
    ? (SSO_ERROR_CODES as readonly string[]).includes(ssoError)
      ? (ssoError as SsoErrorCode)
      : "default"
    : null;
  const brand = settings ?? FALLBACK_SETTINGS;
  const hasSso = (providers?.length ?? 0) > 0;
  const platformName = brand.platform_name;
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    login.mutate(
      { identifier, password },
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
      {/* Admin-authored sign-in notice (#197) — above the card so it's read
          before signing in (event instructions, "use your work account", …). */}
      {brand.login_notice && (
        <Card>
          <CardContent className="py-4">
            <RichTextView value={brand.login_notice} />
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </CardHeader>
        <CardContent>
          {ssoErrorKey && (
            <p
              role="alert"
              className="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {t(`ssoErrors.${ssoErrorKey}`)}
            </p>
          )}

          {hasSso && (
            <div className="mb-4 space-y-2">
              {providers!.map((p) => (
                // A full-page navigation, not fetch(): the IdP redirect chain
                // has to happen in the address bar, not XHR.
                <a
                  key={p.slug}
                  href={p.login_url}
                  className="flex w-full items-center justify-center gap-2 rounded-md border border-border bg-secondary px-4 py-2 text-sm font-medium text-secondary-foreground transition-colors hover:border-primary/50 hover:bg-accent"
                >
                  {/* Renders null for an unbranded provider, so those buttons
                      keep their exact previous appearance (gap needs 2 children). */}
                  <SsoBrandIcon brand={p.brand} className="shrink-0" />
                  {t("ssoSignIn", { name: p.name })}
                </a>
              ))}
              <div className="flex items-center gap-3 pt-2">
                <span className="h-px flex-1 bg-border" />
                <span className="text-xs text-muted-foreground">{t("or")}</span>
                <span className="h-px flex-1 bg-border" />
              </div>
            </div>
          )}

          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="identifier">{t("identifier")}</Label>
              <Input
                id="identifier"
                type="text"
                autoComplete="username"
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="password">{t("password")}</Label>
                <Link
                  href="/forgot-password"
                  className="text-xs text-muted-foreground hover:text-primary hover:underline"
                >
                  {t("forgotPassword")}
                </Link>
              </div>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {login.isError && (
              <p role="alert" className="text-sm text-destructive">
                {(login.error as Error).message}
              </p>
            )}
            <Button type="submit" className="w-full" disabled={login.isPending}>
              {login.isPending ? t("submitting") : t("submit")}
            </Button>
          </form>
          {brand.registration_open && (
            <p className="mt-4 text-sm text-muted-foreground">
              {t("noAccount")}{" "}
              <Link href="/register" className="text-primary hover:underline">
                {t("register")}
              </Link>
            </p>
          )}
        </CardContent>
      </Card>
      {brand.demo_mode && (
        <Card className="border-warning/40">
          <CardHeader className="space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center rounded-full border border-warning/40 bg-warning/10 px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-warning">
                {t("demo.badge")}
              </span>
              <CardTitle className="text-base">{t("demo.title")}</CardTitle>
            </div>
            <CardDescription>
              {t.rich("demo.description", {
                pw: (chunks) => (
                  <span className="font-mono text-foreground">{chunks}</span>
                ),
              })}
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2">
            {DEMO_ACCOUNTS.map((user) => (
              <button
                key={user}
                type="button"
                onClick={() => {
                  setIdentifier(user);
                  setPassword("password");
                }}
                className="group flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/40 px-3 py-2 text-left transition-colors hover:border-primary/50 hover:bg-accent"
              >
                <span className="flex flex-col">
                  <span className="text-sm font-medium">
                    {t(`demo.accounts.${user}.label`)}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {t(`demo.accounts.${user}.description`)}
                  </span>
                </span>
                <span className="shrink-0 rounded-md border border-border bg-background px-2 py-1 font-mono text-xs text-muted-foreground group-hover:text-foreground">
                  {user}
                </span>
              </button>
            ))}
          </CardContent>
        </Card>
      )}
      <LocaleSwitcher className="mx-auto" />
      <PoweredByFooter />
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
