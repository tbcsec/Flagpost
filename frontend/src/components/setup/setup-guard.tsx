"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { useSetupStatus } from "@/lib/hooks/use-setup";

// Forces the whole app to /setup while the instance is unconfigured (no owner
// account yet, ADR-0017). Mounted above every page so it covers the public auth
// screens too. No-op on a configured install (the status query resolves false and
// never flips back). It deliberately does NOT redirect *away* from /setup — the
// /setup page owns the "already configured" case so its error message is readable
// before it forwards on.
export function SetupGuard() {
  const router = useRouter();
  const pathname = usePathname();
  const { data } = useSetupStatus();

  useEffect(() => {
    if (data?.needs_setup && pathname !== "/setup") {
      router.replace("/setup");
    }
  }, [data, pathname, router]);

  return null;
}
