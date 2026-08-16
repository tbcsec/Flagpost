import { LOCALE_COOKIE, type Locale } from "./config";

const ONE_YEAR_S = 60 * 60 * 24 * 365;

/** Persist the user's explicit locale choice. The server request config reads
 *  this cookie on the next render — callers pair it with `router.refresh()`. */
export function setStoredLocale(locale: Locale) {
  document.cookie = `${LOCALE_COOKIE}=${locale}; path=/; max-age=${ONE_YEAR_S}; samesite=lax`;
}
