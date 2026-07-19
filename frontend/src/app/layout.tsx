import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Flagpost",
  description: "Flagpost — open-source CTF competition management platform",
};

// `data-palette` selects the design-system palette (§9); "dark" is the default.
// The token layer in globals.css drives all colour — no inline styles here.
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" data-palette="dark">
      <body className="min-h-screen bg-background text-foreground antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
