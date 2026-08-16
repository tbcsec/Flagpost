// The i18n surface (ADR-0029): which UI locales exist, and how the choice is
// stored. Adding a language is a two-line change here (LOCALES + LOCALE_LABELS)
// plus a `messages/<locale>.json` from Crowdin — no routing or backend work.

export const LOCALES = ["en"] as const;

export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "en";

// The locale choice is a plain cookie, not a users column (ADR-0029): server
// components need it at render time (localStorage doesn't exist there), and the
// login/setup screens need it before anyone is authenticated. `NEXT_LOCALE` is
// the next-intl conventional name.
export const LOCALE_COOKIE = "NEXT_LOCALE";

// Endonyms, deliberately: a user hunting for their language in a UI they can't
// read must see "Deutsch", not "German".
export const LOCALE_LABELS: Record<Locale, string> = {
  en: "English",
};
