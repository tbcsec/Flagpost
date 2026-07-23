"use client";

import * as React from "react";

// The Flagpost logo mark — the flag on the post (LOGO-SPEC §1). A brand asset,
// not an icon: never use it as a bullet, status dot, or affordance (§7).
//
// Colour follows the active palette: on dark grounds the post is the light
// "sheet" and the flag is dark-corrected green; on light it's ink + signal
// green. The mark reads the resolved brand tokens so it recolours with theme.

const PALETTE = {
  light: { post: "hsl(214 33% 9%)", flag: "hsl(156 67% 37%)" },
  dark: { post: "hsl(96 9% 90%)", flag: "hsl(155 61% 44%)" },
} as const;

export interface FlagpostMarkProps {
  size?: number;
  theme?: "light" | "dark";
  className?: string;
  title?: string;
}

export function FlagpostMark({
  size = 32,
  theme = "dark",
  className,
  title = "Flagpost",
}: FlagpostMarkProps) {
  const colors = PALETTE[theme] ?? PALETTE.dark;
  // Below 32px the ground ellipse reads as a smear (LOGO-SPEC §1.2).
  const isSmall = size < 32;

  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label={title}
    >
      {!isSmall && (
        <ellipse cx="22" cy="55" rx="12" ry="3.2" fill={colors.post} />
      )}
      <rect x="19" y="6" width="6" height="49" rx="3" fill={colors.post} />
      <path d="M25 9 H46 L40.5 16 L46 23 H25 Z" fill={colors.flag} />
    </svg>
  );
}

export interface LockupProps {
  size?: number;
  theme?: "light" | "dark";
  className?: string;
  /** The wordmark text — the site's platform name (§9). Defaults to "Flagpost".
   *  The built-in mark never changes; only the name is white-labelled. */
  label?: string;
  /** A custom org logo that replaces the built-in mark (Admin → Appearance). When
   *  set, this image is shown instead of the Flagpost flag mark. */
  logoUrl?: string | null;
  /** Whether the wordmark text renders beside the mark/logo. Orgs whose logo
   *  bakes in their name turn this off. Defaults to true. */
  showWordmark?: boolean;
}

/** The mark + wordmark, horizontally locked up (LOGO-SPEC §4). A custom logo may
 *  swap in for the mark; the wordmark is optional. Flagpost stays attributed via
 *  the mandatory "Powered by Flagpost" footer regardless of branding here. */
export function Lockup({
  size = 28,
  theme = "dark",
  className,
  label = "Flagpost",
  logoUrl = null,
  showWordmark = true,
}: LockupProps) {
  return (
    <span
      className={className}
      style={{ display: "inline-flex", alignItems: "center", gap: size * 0.28 }}
    >
      {logoUrl ? (
        // A dynamic brand asset from the API origin; next/image can't optimize it
        // and would need per-deployment remotePatterns config.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={logoUrl}
          alt={label}
          style={{ height: size, width: "auto", maxWidth: size * 6, objectFit: "contain" }}
        />
      ) : (
        <FlagpostMark size={size} theme={theme} />
      )}
      {showWordmark && (
        <span
          style={{
            fontFamily: "var(--font-display)",
            fontWeight: 700,
            fontSize: size * 0.82,
            letterSpacing: "-0.035em",
            lineHeight: 1,
            color: "hsl(var(--foreground))",
          }}
        >
          {label}
        </span>
      )}
    </span>
  );
}
