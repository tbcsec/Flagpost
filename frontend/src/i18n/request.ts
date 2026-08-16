import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { DEFAULT_LOCALE, LOCALE_COOKIE, LOCALES } from "./config";
import { resolveLocale } from "./negotiate";

// Per-request locale resolution (ADR-0029): explicit cookie choice, then
// Accept-Language, then English (resolveLocale — the precedence is tested
// there). No URL segment and no middleware — reading the cookie here is what
// makes routes render dynamically, which the cookie approach requires anyway
// (a build-time render has nobody's locale).
//
// Deliberately no `timeZone` yet: nothing uses next-intl date/number
// formatting, and hardcoding the container's zone (UTC) would bake in wrong
// user-facing times. The first extraction that formats a date with
// useFormatter() must decide the timezone story first — next-intl warns
// loudly (ENVIRONMENT_FALLBACK) in dev until then.
export default getRequestConfig(async () => {
  const [jar, headerList] = await Promise.all([cookies(), headers()]);
  const locale = resolveLocale(
    jar.get(LOCALE_COOKIE)?.value,
    headerList.get("accept-language") ?? "",
    LOCALES,
    DEFAULT_LOCALE,
  );
  return {
    locale,
    messages: (await import(`../../messages/${locale}.json`)).default,
  };
});
