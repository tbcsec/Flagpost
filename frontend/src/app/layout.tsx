import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "CTF Platform",
  description: "Open-source CTF competition management platform",
};

// No global stylesheet yet: the design-system / Tailwind @theme token layer
// is a Tier 0 feature (ARCHITECTURE.md §9, ROADMAP.md Tier 0 #3), not part
// of this skeleton. Inline styles below are placeholder scaffolding only.
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body
        style={{
          fontFamily: "system-ui, sans-serif",
          margin: 0,
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          background: "#0b0f17",
          color: "#e6edf3",
        }}
      >
        {children}
      </body>
    </html>
  );
}
