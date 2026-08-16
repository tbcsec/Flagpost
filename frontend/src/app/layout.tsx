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

import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Flagpost",
  description: "Flagpost — open-source CTF competition management platform",
};

// `data-palette` selects the design-system palette (§9); Harbor is the shipped
// default. The token layer in globals.css drives all colour. The real theme (the
// admin's site default + the user's palette override + the accent) is applied by
// <ThemeApplier>; the inline script below repaints from the last-known cached
// theme *before* first paint so a non-default theme doesn't flash the default.
const NO_FLASH = `(function(){try{var r=localStorage.getItem('fp:site-theme');if(!r)return;var t=JSON.parse(r),e=document.documentElement,s=e.style;if(t.palette)e.setAttribute('data-palette',t.palette);if(t.mode)e.setAttribute('data-mode',t.mode);if(t.primary){s.setProperty('--primary',t.primary);s.setProperty('--ring',t.ring||t.primary);s.setProperty('--primary-foreground',t.primaryForeground||'0 0% 100%');}}catch(e){}})();`;

export default async function RootLayout({ children }: { children: ReactNode }) {
  // Cookie-resolved locale (ADR-0029, src/i18n/request.ts). Reading it makes
  // every route render per-request — inherent to a cookie-based locale, and
  // fine for an app that was never meaningfully static (auth-gated, client-heavy).
  const [locale, messages] = await Promise.all([getLocale(), getMessages()]);
  return (
    // The NO_FLASH script below intentionally rewrites the palette/mode/accent on
    // <html> *before* hydration from the cached theme, so the server-rendered
    // defaults here won't match the client's first paint. That's expected — so
    // suppress the (one-level) hydration warning on this element, the standard
    // pattern for a pre-hydration theme script.
    <html lang={locale} data-palette="harbor" data-mode="dark" suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased">
        <script dangerouslySetInnerHTML={{ __html: NO_FLASH }} />
        <NextIntlClientProvider locale={locale} messages={messages}>
          <Providers>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
