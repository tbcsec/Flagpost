// Thin fetch helper against the backend API.
//
// Skeleton scope only. The real data-access layer (ARCHITECTURE.md §8) is a
// per-domain TanStack Query hook module under `lib/hooks/`; components call
// those, never this file directly. This helper exists so the hello-world
// page has something to hit before that layer is built (ROADMAP.md Tier 0).

import type { HelloResponse } from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function getHello(): Promise<HelloResponse> {
  const res = await fetch(`${API_URL}/api/hello`);
  if (!res.ok) {
    throw new Error(`Backend responded ${res.status}`);
  }
  return res.json();
}
