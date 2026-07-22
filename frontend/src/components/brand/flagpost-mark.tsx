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
   *  The mark itself never changes; only the name is white-labelled. */
  label?: string;
}

/** The mark + wordmark, horizontally locked up (LOGO-SPEC §4). */
export function Lockup({ size = 28, theme = "dark", className, label = "Flagpost" }: LockupProps) {
  return (
    <span
      className={className}
      style={{ display: "inline-flex", alignItems: "center", gap: size * 0.28 }}
    >
      <FlagpostMark size={size} theme={theme} />
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
    </span>
  );
}
