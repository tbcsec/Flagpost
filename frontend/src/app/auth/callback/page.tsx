"use client";

// The landing page for an SSO redirect (#58, ADR-0021).
//
// The backend's callback has already set the httpOnly refresh cookie; it
// deliberately does *not* put an access token in the URL, since anything in a
// redirect ends up in browser history, the Referer header, and any proxy log in
// between. So this page performs the same handshake the app does on a normal
// reload: call /api/auth/refresh, put the access token in memory, and continue.

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef } from "react";

import { PoweredByFooter } from "@/components/app/powered-by-footer";
import { Lockup } from "@/components/brand/flagpost-mark";
import { Skeleton } from "@/components/ui/skeleton";
import { useRestoreSession } from "@/lib/hooks/use-users";
import { FALLBACK_SETTINGS, useSiteSettings } from "@/lib/hooks/use-site-settings";

function CallbackInner() {
  const router = useRouter();
  const params = useSearchParams();
  const restore = useRestoreSession();
  const { data: settings } = useSiteSettings();
  const brand = settings ?? FALLBACK_SETTINGS;
  // React 18 StrictMode double-invokes effects in dev; the refresh call rotates
  // the session, so guard against running it twice.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const next = params.get("next");
    // Same allowlist the backend applies, for the same reason: a "starts with /
    // but not //" check misses `/\evil.com`, which browsers normalise into a
    // protocol-relative URL. The backend validates this too — this is the
    // second lock, not the only one.
    const destination =
      next && /^\/(?!\/)[A-Za-z0-9\-._~!$&'()*+,;=:@%/?#[\]]*$/.test(next) ? next : "/";

    restore
      .mutateAsync()
      .then((ok) => router.replace(ok ? destination : "/login?error=default"))
      .catch(() => router.replace("/login?error=default"));
    // `restore` and `router` are stable for this component's life; re-running
    // on their identity would defeat the once-only guard above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 p-8">
      <div className="flex justify-center">
        <Lockup
          size={40}
          theme="dark"
          label={brand.platform_name}
          logoUrl={brand.logo_url}
          showWordmark={brand.show_wordmark}
        />
      </div>
      <div className="space-y-3 text-center">
        <p className="text-sm text-muted-foreground">Signing you in…</p>
        <Skeleton className="h-2 w-full" />
      </div>
      <PoweredByFooter />
    </main>
  );
}

export default function AuthCallbackPage() {
  // useSearchParams needs a Suspense boundary under the App Router.
  return (
    <Suspense fallback={null}>
      <CallbackInner />
    </Suspense>
  );
}
