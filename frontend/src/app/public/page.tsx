"use client";

import Link from "next/link";

import { LocaleSwitcher } from "@/components/app/locale-switcher";
import { PoweredByFooter } from "@/components/app/powered-by-footer";
import { Lockup } from "@/components/brand/flagpost-mark";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { FALLBACK_SETTINGS, useSiteSettings } from "@/lib/hooks/use-site-settings";
import { usePublicCompetitions } from "@/lib/hooks/use-public-scoreboard";

// The public directory (no login): competitions that opted into a public
// scoreboard. Selecting one opens its standalone board at /public/<id>.
export default function PublicDirectoryPage() {
  const { data, isLoading } = usePublicCompetitions();
  const { data: settings } = useSiteSettings();
  const brand = settings ?? FALLBACK_SETTINGS;

  return (
    <div className="mx-auto flex min-h-dvh max-w-3xl flex-col gap-6 px-4 py-8">
      <header>
        <Lockup
          size={32}
          label={brand.platform_name}
          logoUrl={brand.logo_url}
          showWordmark={brand.show_wordmark}
        />
      </header>

      <div>
        <h1 className="text-2xl font-semibold">Public scoreboards</h1>
        <p className="text-sm text-muted-foreground">
          Live standings for competitions open to spectators — no account needed.
        </p>
      </div>

      {isLoading && <Skeleton className="h-40 w-full" />}

      {data && data.length === 0 && (
        <Card>
          <CardContent className="p-8 text-center text-sm text-muted-foreground">
            No public scoreboards are available right now.
          </CardContent>
        </Card>
      )}

      {data && data.length > 0 && (
        <div className="grid gap-3">
          {data.map((c) => (
            <Link
              key={c.id}
              href={`/public/${c.id}`}
              className="rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary/40"
            >
              <div className="text-base font-semibold">{c.name}</div>
              <div className="text-xs text-muted-foreground">
                {c.participation_mode === "team" ? "Team" : "Individual"} competition
                {c.end_at && ` · ends ${new Date(c.end_at).toLocaleDateString()}`}
              </div>
            </Link>
          ))}
        </div>
      )}

      <div className="mt-auto flex flex-col items-center">
        <LocaleSwitcher />
        <PoweredByFooter />
      </div>
    </div>
  );
}
