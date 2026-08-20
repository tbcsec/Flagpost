"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { AppShell } from "@/components/app/app-shell";
import { PoweredByFooter } from "@/components/app/powered-by-footer";
import { Lockup } from "@/components/brand/flagpost-mark";
import { Card, CardContent } from "@/components/ui/card";
import { RichTextView } from "@/components/ui/rich-text-view";
import { Skeleton } from "@/components/ui/skeleton";
import { usePage } from "@/lib/hooks/use-pages";
import { FALLBACK_SETTINGS, useSiteSettings } from "@/lib/hooks/use-site-settings";
import { useAuthStore } from "@/stores/auth";
import type { PageContent } from "@/lib/types";

// A custom page (#198, ADR-0034), rendered at /p/{slug}.
//
// Deliberately **outside** the `(app)` route group: that layout bounces
// anonymous visitors to /login, and a page published `public` has to be
// readable logged-out. Route groups don't change the URL, so `(app)/p/[slug]`
// and `p/[slug]` would resolve to the same path and can't both exist — this is
// the only side of that fork that serves signed-out readers.
//
// The cost of living outside the shell is that we lose the sidebar, so an
// authenticated reader gets it back explicitly below. A signed-out reader gets
// standalone chrome instead, matching /public.
//
// Body rendering goes through `RichTextView` — a React tree under ProseMirror's
// schema, never an HTML string. That is the whole security posture of the
// feature (ADR-0034); nothing here may substitute `dangerouslySetInnerHTML`,
// however convenient a server-rendered body would be for SEO.

function PageBody({ page }: { page: PageContent }) {
  return (
    <article className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold text-foreground">{page.title}</h1>
      {page.content ? (
        <RichTextView value={page.content} />
      ) : (
        // A page with no body isn't an error — it's an author who hasn't
        // written one yet, and the title alone may be the whole point (a
        // placeholder someone linked early).
        <p className="text-sm text-muted-foreground">
          This page doesn&apos;t have any content yet.
        </p>
      )}
    </article>
  );
}

function NotFound() {
  // Matches the API's stance: a page that is missing, still a draft, or
  // members-only to a signed-out reader all look identical here, so the UI
  // can't confirm a page exists to someone who may not read it (ADR-0034).
  return (
    <div className="flex flex-col gap-2">
      <h1 className="text-2xl font-semibold text-foreground">Page not found</h1>
      <p className="text-sm text-muted-foreground">
        This page doesn&apos;t exist, or you don&apos;t have access to it.
      </p>
      <Link href="/" className="text-sm text-primary hover:underline">
        Back to Flagpost
      </Link>
    </div>
  );
}

function Content({ slug }: { slug: string }) {
  const { data, isLoading, isError } = usePage(slug);
  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-8 w-1/3" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
      </div>
    );
  }
  if (isError || !data) return <NotFound />;
  return <PageBody page={data} />;
}

export default function CustomPage() {
  const params = useParams<{ slug: string }>();
  const slug = typeof params?.slug === "string" ? params.slug : "";
  const status = useAuthStore((s) => s.status);
  const { data: settings } = useSiteSettings();
  const brand = settings ?? FALLBACK_SETTINGS;

  // Wait for the session to resolve before choosing chrome, or an authenticated
  // reader sees the signed-out layout flash before the sidebar appears.
  if (status === "loading") {
    return (
      <main className="flex min-h-dvh items-center justify-center">
        <Skeleton className="h-24 w-full max-w-2xl" />
      </main>
    );
  }

  if (status === "authenticated") {
    return (
      <AppShell>
        <div className="mx-auto w-full max-w-3xl">
          <Content slug={slug} />
        </div>
      </AppShell>
    );
  }

  return (
    <div className="mx-auto flex min-h-dvh max-w-3xl flex-col gap-6 px-4 py-8">
      <header>
        <Link href="/login">
          <Lockup
            label={brand.platform_name}
            logoUrl={brand.logo_url}
            showWordmark={brand.show_wordmark}
          />
        </Link>
      </header>
      <Card>
        <CardContent className="py-6">
          <Content slug={slug} />
        </CardContent>
      </Card>
      <PoweredByFooter />
    </div>
  );
}
