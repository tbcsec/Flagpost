"use client";

import * as React from "react";

// Official sign-in marks for the SSO login buttons and the admin quick-setup
// cards: the Google "G" and the Microsoft four-square. Brand assets, not
// icons — like flagpost-mark.tsx, this directory is deliberately exempt from
// the no-raw-hex ESLint rule (§9), because these colours are fixed by Google's
// and Microsoft's brand guidelines and must never follow the theme. The eight
// hexes below live in src/components/brand/ and nowhere else.
//
// Both marks render aria-hidden: the button text already names the provider,
// so the mark is decoration to a screen reader.

export interface SsoBrandIconProps {
  /** The provider's server-derived brand ("google" | "microsoft"); anything
   *  else — including null for a plain OIDC/SAML provider — renders nothing. */
  brand: string | null | undefined;
  className?: string;
  size?: number;
}

function GoogleMark({ className, size = 16 }: { className?: string; size?: number }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 18 18"
      aria-hidden="true"
      focusable="false"
      data-brand-icon="google"
    >
      <path
        fill="#4285F4"
        d="M17.64 9.2045c0-.6381-.0573-1.2518-.1636-1.8409H9v3.4814h4.8436c-.2086 1.125-.8427 2.0782-1.7959 2.7164v2.2581h2.9087c1.7018-1.5668 2.6836-3.874 2.6836-6.615z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.4673-.8059 5.9564-2.1805l-2.9087-2.2581c-.8059.54-1.8368.859-3.0477.859-2.344 0-4.3282-1.5831-5.036-3.7104H.9574v2.3318C2.4382 15.9832 5.4818 18 9 18z"
      />
      <path
        fill="#FBBC05"
        d="M3.964 10.71c-.18-.54-.2822-1.1168-.2822-1.71s.1022-1.17.2822-1.71V4.9582H.9574A8.9965 8.9965 0 0 0 0 9c0 1.4523.3477 2.8268.9574 4.0418L3.964 10.71z"
      />
      <path
        fill="#EA4335"
        d="M9 3.5795c1.3214 0 2.5077.4541 3.4405 1.346l2.5813-2.5814C13.4632.8918 11.4259 0 9 0 5.4818 0 2.4382 2.0168.9574 4.9582L3.964 7.29C4.6718 5.1627 6.6559 3.5795 9 3.5795z"
      />
    </svg>
  );
}

function MicrosoftMark({ className, size = 16 }: { className?: string; size?: number }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 21 21"
      aria-hidden="true"
      focusable="false"
      data-brand-icon="microsoft"
    >
      <rect x="1" y="1" width="9" height="9" fill="#F25022" />
      <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
      <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
      <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
    </svg>
  );
}

/** The matching brand mark, or null for an unknown/absent brand — callers can
 *  render it unconditionally and non-branded providers keep their exact
 *  unadorned appearance. */
export function SsoBrandIcon({ brand, className, size }: SsoBrandIconProps) {
  if (brand === "google") return <GoogleMark className={className} size={size} />;
  if (brand === "microsoft") return <MicrosoftMark className={className} size={size} />;
  return null;
}
