"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

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
import { Select } from "@/components/ui/select";
import { useCompleteSetup, useSetupStatus } from "@/lib/hooks/use-setup";
import { ACCENTS, PALETTES, applyTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";

// First-run setup (ADR-0017). Gate the render on the server-confirmed status so
// the wizard **only mounts when the instance is genuinely unconfigured** — a
// configured install never flashes a usable wizard before the SetupGuard's
// redirect fires (it shows an error instead). Provisioning is also refused
// server-side (POST /api/setup 409s once an admin exists), so setup can't be run
// twice even if the request is crafted by hand.
export default function SetupPage() {
  const router = useRouter();
  const authStatus = useAuthStore((s) => s.status);
  const { data, isLoading } = useSetupStatus();
  const configured = !!data && !data.needs_setup;
  // An authenticated visitor on a configured install (e.g. the admin who just
  // finished, or one browsing here) goes straight to the app — no error.
  const quietRedirect = configured && authStatus === "authenticated";

  // A configured install owns the redirect so the error is readable first (the
  // SetupGuard no longer yanks away instantly).
  useEffect(() => {
    if (!configured) return;
    if (authStatus === "authenticated") {
      router.replace("/");
      return;
    }
    const t = setTimeout(() => router.replace("/login"), 3000);
    return () => clearTimeout(t);
  }, [configured, authStatus, router]);

  if (isLoading || !data || quietRedirect) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </main>
    );
  }

  if (!data.needs_setup) {
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 p-8">
        <div className="flex justify-center">
          <Lockup size={40} theme="dark" />
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Setup already completed</CardTitle>
            <CardDescription>
              This instance has already been configured — setup can only run once.
              Redirecting you to sign in…
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild className="w-full">
              <Link href="/login">Go to sign in</Link>
            </Button>
          </CardContent>
        </Card>
      </main>
    );
  }

  return <SetupWizard />;
}

function SetupWizard() {
  const router = useRouter();
  const complete = useCompleteSetup();

  const [step, setStep] = useState(0);

  // Step 1 — owner account.
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");

  // Step 2 — branding.
  const [platformName, setPlatformName] = useState("Flagpost");
  const [palette, setPalette] = useState("harbor");
  const [accent, setAccent] = useState("signal");

  // Step 3 — site options.
  const [registrationOpen, setRegistrationOpen] = useState(true);

  // Live-preview the chosen theme on the wizard itself.
  useEffect(() => {
    applyTheme(document.documentElement, { palette, accent });
  }, [palette, accent]);

  const accountValid =
    displayName.trim().length > 0 && password.length >= 8 && password === confirm;

  function onFinish() {
    complete.mutate(
      {
        admin: {
          display_name: displayName.trim(),
          password,
          email: email.trim() || undefined,
        },
        platform_name: platformName.trim() || "Flagpost",
        default_palette: palette,
        accent,
        registration_open: registrationOpen,
      },
      {
        onSuccess: () => router.replace("/"),
        onError: (e) =>
          toast("Setup failed", { description: (e as Error).message, variant: "destructive" }),
      },
    );
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-6 p-8">
      <div className="flex flex-col items-center gap-2">
        <Lockup size={40} theme="dark" label={platformName || "Flagpost"} />
        <p className="text-sm text-muted-foreground">Welcome — let&apos;s set up your instance.</p>
      </div>

      <div className="flex items-center justify-center gap-2" aria-hidden>
        {["Account", "Branding", "Options"].map((name, i) => (
          <div key={name} className="flex items-center gap-2">
            <span
              className={cn(
                "flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold",
                i <= step ? "bg-primary text-primary-foreground" : "bg-secondary text-secondary-foreground",
              )}
            >
              {i + 1}
            </span>
            <span className={cn("text-xs", i === step ? "font-medium text-foreground" : "text-muted-foreground")}>
              {name}
            </span>
            {i < 2 && <span className="mx-1 h-px w-6 bg-border" />}
          </div>
        ))}
      </div>

      <Card>
        {step === 0 && (
          <>
            <CardHeader>
              <CardTitle>Administrator account</CardTitle>
              <CardDescription>The owner account. Your username is how you sign in.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="dn">Username</Label>
                <Input id="dn" autoComplete="username" value={displayName} onChange={(e) => setDisplayName(e.target.value)} required />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="em">Email (optional)</Label>
                <Input id="em" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="pw">Password</Label>
                <Input id="pw" type="password" autoComplete="new-password" minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} required />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="cf">Confirm password</Label>
                <Input id="cf" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
                {confirm.length > 0 && password !== confirm && (
                  <p role="alert" className="text-xs text-destructive">Passwords don&apos;t match.</p>
                )}
              </div>
            </CardContent>
          </>
        )}

        {step === 1 && (
          <>
            <CardHeader>
              <CardTitle>Branding</CardTitle>
              <CardDescription>Name and colours for your platform. You can add a logo later on Admin → Site settings → Appearance.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-5">
              <div className="grid gap-2">
                <Label htmlFor="pn">Platform name</Label>
                <Input id="pn" value={platformName} maxLength={64} onChange={(e) => setPlatformName(e.target.value)} />
              </div>
              <div className="grid gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Palette</span>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {PALETTES.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => setPalette(p.id)}
                      className={cn(
                        "grid gap-1.5 rounded-lg border p-2 text-left transition-colors",
                        palette === p.id ? "border-primary ring-1 ring-primary" : "border-border hover:border-primary/40",
                      )}
                    >
                      <span className="h-8 rounded" style={{ backgroundColor: p.swatch.bg, borderColor: p.swatch.border }} />
                      <span className="text-xs font-medium">{p.label}</span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Accent</span>
                <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                  {ACCENTS.map((a) => (
                    <button
                      key={a.id}
                      type="button"
                      onClick={() => setAccent(a.id)}
                      title={a.label}
                      className={cn(
                        "grid gap-1 rounded-lg border p-1.5 transition-colors",
                        accent === a.id ? "border-primary ring-1 ring-primary" : "border-border hover:border-primary/40",
                      )}
                    >
                      <span className="h-6 w-full rounded" style={{ backgroundColor: a.hex }} />
                    </button>
                  ))}
                </div>
              </div>
            </CardContent>
          </>
        )}

        {step === 2 && (
          <>
            <CardHeader>
              <CardTitle>Site options</CardTitle>
              <CardDescription>One last thing. These are all editable later in Admin.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="reg">Public registration</Label>
                <Select id="reg" value={registrationOpen ? "open" : "closed"} onChange={(e) => setRegistrationOpen(e.target.value === "open")}>
                  <option value="open">Open — anyone can create an account</option>
                  <option value="closed">Closed — you create accounts (Admin → Users)</option>
                </Select>
              </div>
              <div className="rounded-md border border-border bg-muted/40 p-3 text-sm">
                <p className="mb-1 font-medium">Ready to go</p>
                <p className="text-xs text-muted-foreground">
                  Owner <span className="font-medium text-foreground">{displayName || "—"}</span> ·
                  Platform <span className="font-medium text-foreground">{platformName || "Flagpost"}</span> ·
                  Registration {registrationOpen ? "open" : "closed"}
                </p>
              </div>
            </CardContent>
          </>
        )}

        <CardContent className="flex items-center justify-between border-t border-border pt-4">
          <Button type="button" variant="ghost" onClick={() => setStep((s) => s - 1)} disabled={step === 0}>
            Back
          </Button>
          {step < 2 ? (
            <Button type="button" onClick={() => setStep((s) => s + 1)} disabled={step === 0 && !accountValid}>
              Next
            </Button>
          ) : (
            <Button type="button" onClick={onFinish} disabled={!accountValid || complete.isPending}>
              {complete.isPending ? "Setting up…" : "Finish setup"}
            </Button>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
