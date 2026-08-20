"use client";

// One hook module per domain (ARCHITECTURE.md §8). Custom pages (#198,
// ADR-0034): admin-authored site-level content in the sidebar, rendered at
// `/p/{slug}`.
//
// The two reads are public — a page may be published `public`, and the nav list
// drives the sidebar for signed-out visitors too. Authoring is behind
// `manage_pages`.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { pagesApi } from "@/lib/api";
import type { AdminPage, PageWrite } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

const PAGES_NAV_KEY = ["pages", "nav"] as const;
const PAGES_ADMIN_KEY = ["pages", "admin"] as const;

/** Sidebar entries the current viewer may see.
 *
 * The same endpoint serves both audiences — anonymous gets public pages, a
 * signed-in viewer gets public + members-only — so the request must actually
 * carry the token when one exists, and the **query key must include which
 * slice was fetched**. Without the key, the anonymous list cached on /login
 * survives into the signed-in session and members-only pages silently never
 * appear (the launch bug this fixes). `enabled` waits out session hydration so
 * the wrong slice is never fetched-and-cached during the loading window.
 */
export function usePageNav() {
  const status = useAuthStore((s) => s.status);
  const authed = status === "authenticated";
  return useQuery({
    queryKey: [...PAGES_NAV_KEY, authed],
    queryFn: () => pagesApi.nav(authed),
    enabled: status !== "loading",
    staleTime: 5 * 60 * 1000,
  });
}

/** One page's content. `enabled` also guards the empty-slug render Next does
 *  before route params resolve. Keyed by auth for the same reason as the nav:
 *  a members-only page 404s anonymously, and that cached 404 must not outlive
 *  signing in. */
export function usePage(slug: string | undefined) {
  const status = useAuthStore((s) => s.status);
  const authed = status === "authenticated";
  return useQuery({
    queryKey: ["pages", "detail", slug ?? "", authed],
    queryFn: () => pagesApi.get(slug as string, authed),
    enabled: Boolean(slug) && status !== "loading",
    // A 404 here is a real answer (no such page, or not visible to this
    // viewer), not a transient failure — retrying just delays the empty state.
    retry: false,
  });
}

/** Every page including drafts — `manage_pages` only. */
export function useAdminPages() {
  return useQuery({ queryKey: PAGES_ADMIN_KEY, queryFn: pagesApi.adminList });
}

/** Invalidate both the authoring list and the public nav.
 *
 * Every mutation can change what the sidebar shows — publishing a draft, making
 * a page members-only, renaming or reordering it — so refreshing only the admin
 * list would leave the author looking at a stale sidebar and doubting the save.
 */
function useInvalidatePages() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: PAGES_ADMIN_KEY });
    void qc.invalidateQueries({ queryKey: PAGES_NAV_KEY });
    void qc.invalidateQueries({ queryKey: ["pages", "detail"] });
  };
}

export function useCreatePage() {
  const invalidate = useInvalidatePages();
  return useMutation({
    mutationFn: (input: PageWrite) => pagesApi.create(input),
    onSuccess: invalidate,
  });
}

export function useUpdatePage() {
  const invalidate = useInvalidatePages();
  return useMutation({
    mutationFn: ({ id, ...input }: Partial<PageWrite> & { id: string }) =>
      pagesApi.update(id, input),
    onSuccess: invalidate,
  });
}

export function useDeletePage() {
  const invalidate = useInvalidatePages();
  return useMutation({
    mutationFn: (id: string) => pagesApi.remove(id),
    onSuccess: invalidate,
  });
}

export function useReorderPages() {
  const invalidate = useInvalidatePages();
  return useMutation({
    mutationFn: (pages: AdminPage[]) =>
      pagesApi.reorder(pages.map((page) => page.id)),
    onSuccess: invalidate,
  });
}
