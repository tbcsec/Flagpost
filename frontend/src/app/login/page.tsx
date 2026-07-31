"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
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
import { useAuthProviders, useLogin } from "@/lib/hooks/use-users";
import { useSearchParams } from "next/navigation";

// The callback redirects here with a short code rather than the provider's own
// message — a failure is usually a misconfiguration whose detail (endpoints,
// client ids, internal hostnames) shouldn't be reflected to a browser. Server
// logs carry the specifics.
const SSO_ERRORS: Record<string, string> = {
  invalid_state:
    "That sign-in link has expired or was already used. Please try again.",
  expired: "That sign-in attempt timed out. Please try again.",
  invalid_token: "We couldn't verify the response from your identity provider.",
  provider_unavailable:
    "That identity provider isn't reachable right now. Try again, or sign in with a password.",
  provider_denied: "Your identity provider declined the sign-in request.",
  invalid_response: "Your identity provider sent an incomplete response.",
  account_disabled: "That account has been disabled. Contact an administrator.",
  default: "Single sign-on failed. Please try again, or sign in with a password.",
};

// Shown only on a demo instance (seeded by auth/demo.py). Password is "password".
const DEMO_ACCOUNTS = [
  { user: "admin", label: "Administrator", desc: "full platform control" },
  { user: "judge", label: "Judge", desc: "run a competition" },
  { user: "participant", label: "Participant", desc: "solve challenges" },
];

export default function LoginPage() {
  const router = useRouter();
  const login = useLogin();
  const { data: settings } = useSiteSettings();
  const { data: providers } = useAuthProviders();
  const searchParams = useSearchParams();
  const ssoError = searchParams.get("error");
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
      <Card>
        <CardHeader>
          <CardTitle>Sign in</CardTitle>
          <CardDescription>Access your competitions.</CardDescription>
        </CardHeader>
        <CardContent>
          {ssoError && (
            <p
              role="alert"
              className="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              {SSO_ERRORS[ssoError] ?? SSO_ERRORS.default}
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
                  className="flex w-full items-center justify-center rounded-md border border-border bg-secondary px-4 py-2 text-sm font-medium text-secondary-foreground transition-colors hover:border-primary/50 hover:bg-accent"
                >
                  Sign in with {p.name}
                </a>
              ))}
              <div className="flex items-center gap-3 pt-2">
                <span className="h-px flex-1 bg-border" />
                <span className="text-xs text-muted-foreground">or</span>
                <span className="h-px flex-1 bg-border" />
              </div>
            </div>
          )}

          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="identifier">Username or email</Label>
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
                <Label htmlFor="password">Password</Label>
                <Link
                  href="/forgot-password"
                  className="text-xs text-muted-foreground hover:text-primary hover:underline"
                >
                  Forgot password?
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
              {login.isPending ? "Signing in…" : "Sign in"}
            </Button>
          </form>
          {brand.registration_open && (
            <p className="mt-4 text-sm text-muted-foreground">
              No account?{" "}
              <Link href="/register" className="text-primary hover:underline">
                Register
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
                Demo
              </span>
              <CardTitle className="text-base">Try it instantly</CardTitle>
            </div>
            <CardDescription>
              Click an account to fill the form above — the password is{" "}
              <span className="font-mono text-foreground">password</span>. Data
              is public and resets every hour, on the hour.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2">
            {DEMO_ACCOUNTS.map((a) => (
              <button
                key={a.user}
                type="button"
                onClick={() => {
                  setIdentifier(a.user);
                  setPassword("password");
                }}
                className="group flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/40 px-3 py-2 text-left transition-colors hover:border-primary/50 hover:bg-accent"
              >
                <span className="flex flex-col">
                  <span className="text-sm font-medium">{a.label}</span>
                  <span className="text-xs text-muted-foreground">{a.desc}</span>
                </span>
                <span className="shrink-0 rounded-md border border-border bg-background px-2 py-1 font-mono text-xs text-muted-foreground group-hover:text-foreground">
                  {a.user}
                </span>
              </button>
            ))}
          </CardContent>
        </Card>
      )}
      <PoweredByFooter />
    </main>
  );
}
