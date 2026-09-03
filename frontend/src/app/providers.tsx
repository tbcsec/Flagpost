"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { RouteProgress } from "@/components/app/route-progress";
import { SetupGuard } from "@/components/setup/setup-guard";
import { BrandProvider } from "@/components/theme/brand-context";
import { SiteBackground } from "@/components/theme/site-background";
import { ThemeApplier } from "@/components/theme/theme-applier";
import { ConfirmProvider } from "@/components/ui/confirm";
import { Toaster } from "@/components/ui/toaster";
import type { BrandSnapshot } from "@/lib/brand";
import { authApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

// Defaults per §8: short-but-non-zero staleTime (real-time updates arrive over
// the WebSocket layer later, not via polling) and no refetch-on-focus.
function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        refetchOnWindowFocus: false,
        retry: 1,
      },
    },
  });
}

/** Restore the session from the httpOnly refresh cookie once on load. */
function SessionRestorer() {
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    // Restore the persisted active-competition selection (#316) synchronously,
    // before the auth-gated shell mounts, so a reload keeps the user's
    // competition instead of snapping to the first one. The shell re-validates
    // the restored id against the competitions the user can see.
    useAuthStore.getState().hydrateActiveCompetition();
    void authApi.restore();
  }, []);
  return null;
}

export function Providers({
  children,
  initialBrand,
}: {
  children: React.ReactNode;
  /** The server-resolved branding (#362) — seeds useSiteSettings' placeholder
   *  so the first client render matches the server-painted HTML. */
  initialBrand: BrandSnapshot;
}) {
  const [queryClient] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <BrandProvider value={initialBrand}>
        <SessionRestorer />
        <ThemeApplier />
        <SiteBackground />
        <SetupGuard />
        <RouteProgress />
        <ConfirmProvider>{children}</ConfirmProvider>
        <Toaster />
      </BrandProvider>
    </QueryClientProvider>
  );
}
