"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

// /admin has no page of its own — it lands on the Dashboard tab.
export default function AdminIndex() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/admin/dashboard");
  }, [router]);
  return null;
}
