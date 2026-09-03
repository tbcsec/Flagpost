import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";
import type { ReactNode } from "react";

// Self-hosted brand/display face (LOGO-SPEC) — vendored via @fontsource so it
// works offline/air-gapped with no runtime Google Fonts request (and a clean
// `font-src 'self'` CSP). Registers the "Space Grotesk" family that
// `--font-display` (globals.css) references.
import "@fontsource/space-grotesk/400.css";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/space-grotesk/600.css";
import "@fontsource/space-grotesk/700.css";

import { brandStyleVars } from "@/lib/brand";
import { getServerBrand } from "@/lib/server/branding";

import { Providers } from "./providers";
import "./globals.css";

// The tab title is branding too (§9) — serving the platform name from the
// first response beats the old static "Flagpost" that a client effect
// overwrote only after the settings fetch. getServerBrand is request-cached,
// so this shares its work with the layout below.
export async function generateMetadata(): Promise<Metadata> {
  const brand = await getServerBrand();
  return {
    title: brand.platformName,
    // Branded, not hardcoded: link unfurls/search snippets on a white-labeled
    // instance must not leak the product name (the in-app "Powered by
    // Flagpost" footer remains the attribution surface).
    description: `${brand.platformName} — CTF competition platform`,
  };
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  // Cookie-resolved locale (ADR-0029, src/i18n/request.ts). Reading it makes
  // every route render per-request — inherent to a cookie-based locale, and
  // fine for an app that was never meaningfully static (auth-gated, client-heavy).
  //
  // Branding rides the same per-request render (#362): the `fp_brand` cookie
  // (kept warm by ThemeApplier, including the viewer's own palette override) —
  // or a cold-start backend fetch — is resolved server-side and painted into
  // the initial HTML, so a rebranded instance never flashes the defaults.
  const [locale, messages, brand] = await Promise.all([
    getLocale(),
    getMessages(),
    getServerBrand(),
  ]);
  return (
    // suppressHydrationWarning stays (one level): browser extensions commonly
    // mutate <html> attributes before hydration, and ThemeApplier re-applies
    // the theme post-hydration — the standard pattern for a themed root.
    <html
      lang={locale}
      data-palette={brand.palette}
      data-mode={brand.mode}
      style={brandStyleVars(brand)}
      suppressHydrationWarning
    >
      <body className="min-h-screen bg-background text-foreground antialiased">
        {/* Serializes the full catalog into every response — fine at today's
            size; switch to a per-namespace pick when extraction grows the
            catalog (ADR-0029, consequences). */}
        <NextIntlClientProvider locale={locale} messages={messages}>
          <Providers initialBrand={brand}>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
