import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { DEFAULT_LOCALE, LOCALE_COOKIE, LOCALES } from "./config";
import { negotiateLocale } from "./negotiate";

// Per-request locale resolution (ADR-0029): explicit cookie choice, then
// Accept-Language, then English. No URL segment and no middleware — reading the
// cookie here is what makes routes render dynamically, which the cookie
// approach requires anyway (a build-time render has nobody's locale).
export default getRequestConfig(async () => {
  const jar = await cookies();
  const fromCookie = jar.get(LOCALE_COOKIE)?.value;
  let locale = LOCALES.find((l) => l === fromCookie);
  if (!locale) {
    const acceptLanguage = (await headers()).get("accept-language") ?? "";
    locale = negotiateLocale(acceptLanguage, LOCALES) ?? DEFAULT_LOCALE;
  }
  return {
    locale,
    messages: (await import(`../../messages/${locale}.json`)).default,
  };
});
