"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { AppShell } from "@/components/app/app-shell";
import { useAuthStore } from "@/stores/auth";

// The authenticated surface. Everything under (app) renders inside the shell
// (sidebar + topbar); anonymous visitors are bounced to /login. Route groups
// don't affect the URL, so these pages live at /, /challenges, /admin/*, etc.
export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const status = useAuthStore((s) => s.status);

  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
  }, [status, router]);

  if (status !== "authenticated") {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </main>
    );
  }

  return <AppShell>{children}</AppShell>;
}
