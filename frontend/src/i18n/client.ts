import { setCookie } from "@/lib/cookies";

import { LOCALE_COOKIE, type Locale } from "./config";

/** Persist the user's explicit locale choice. The server request config reads
 *  this cookie on the next render — callers pair it with `router.refresh()`. */
export function setStoredLocale(locale: Locale) {
  setCookie(LOCALE_COOKIE, locale);
}
