"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { firstAdminHref } from "@/lib/admin-surfaces";
import { useAccess } from "@/lib/hooks/use-permissions";

// /admin has no page of its own — it lands on the first Admin page this viewer
// can open (#477): the Dashboard for an administrator, the Event log for an
// auditor-only delegate. With nothing to open, the shell's "no access" notice
// is what they see, so the dashboard route is as good a place as any.
export default function AdminIndex() {
  const router = useRouter();
  const access = useAccess();
  // A string, so the effect runs once per destination rather than per render
  // (useAccess hands back fresh predicate functions every time).
  const target = access.ready ? (firstAdminHref(access.hasGlobal) ?? "/admin/dashboard") : null;
  useEffect(() => {
    if (target) router.replace(target);
  }, [target, router]);
  return null;
}
