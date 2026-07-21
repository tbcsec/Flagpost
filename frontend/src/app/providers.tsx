"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { Toaster } from "@/components/ui/toaster";
import { authApi } from "@/lib/api";

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
    void authApi.restore();
  }, []);
  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <SessionRestorer />
      {children}
      <Toaster />
    </QueryClientProvider>
  );
}
