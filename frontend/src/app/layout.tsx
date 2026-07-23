import type { Metadata } from "next";
import type { ReactNode } from "react";

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

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // The NO_FLASH script below intentionally rewrites the palette/mode/accent on
    // <html> *before* hydration from the cached theme, so the server-rendered
    // defaults here won't match the client's first paint. That's expected — so
    // suppress the (one-level) hydration warning on this element, the standard
    // pattern for a pre-hydration theme script.
    <html lang="en" data-palette="harbor" data-mode="dark" suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased">
        <script dangerouslySetInnerHTML={{ __html: NO_FLASH }} />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
