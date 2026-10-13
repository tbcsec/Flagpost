"use client";

// The product changelog (/changelog) — every release, its headline features,
// the date it shipped, and a link to the full GitHub release notes.
//
// Outside the `(app)` route group for the same reason as /p/[slug]: the footer
// links here from the signed-out auth screens too, so the page must be readable
// logged-out. An authenticated reader gets the shell back explicitly; a
// signed-out one gets standalone chrome.
//
// Content comes from the bundled lib/changelog.ts (no runtime GitHub calls —
// nothing phones home); release text is product data and stays literal English,
// while the chrome below is extracted (ADR-0029, born-extracted rule).

import Link from "next/link";
import { useTranslations } from "next-intl";

import { AppShell } from "@/components/app/app-shell";
import { PoweredByFooter } from "@/components/app/powered-by-footer";
import { Lockup } from "@/components/brand/flagpost-mark";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CHANGELOG } from "@/lib/changelog";
import { useBrandSettings } from "@/lib/hooks/use-site-settings";
import { useAuthStore } from "@/stores/auth";

function ChangelogBody() {
  const t = useTranslations("changelog");
  return (
    <article className="flex flex-col gap-8">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold text-foreground">{t("title")}</h1>
        <p className="text-sm text-muted-foreground">{t("description")}</p>
      </header>
      {CHANGELOG.map((release) => (
        <section key={release.version} className="flex flex-col gap-3">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 className="text-lg font-semibold text-foreground">
              {release.version}
            </h2>
            <Badge variant="secondary">
              {t("releasedOn", {
                date: new Date(release.date).toLocaleDateString(undefined, {
                  year: "numeric",
                  month: "long",
                  day: "numeric",
                }),
              })}
            </Badge>
          </div>
          {/* Release title + bullets are product data — literal by design. */}
          <p className="text-sm font-medium text-foreground">{release.title}</p>
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted-foreground">
            {release.highlights.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <a
            href={release.url}
            target="_blank"
            rel="noreferrer noopener"
            className="text-sm text-primary hover:underline"
          >
            {t("viewRelease", { version: release.version })}
          </a>
        </section>
      ))}
    </article>
  );
}

export default function ChangelogPage() {
  const status = useAuthStore((s) => s.status);
  const brand = useBrandSettings();

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
          <ChangelogBody />
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
          <ChangelogBody />
        </CardContent>
      </Card>
      <PoweredByFooter />
    </div>
  );
}
