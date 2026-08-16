"use client";

import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { Select } from "@/components/ui/select";
import { setStoredLocale } from "@/i18n/client";
import { LOCALE_LABELS, LOCALES, type Locale } from "@/i18n/config";

/** Language picker (ADR-0029). Renders nothing while only one locale ships, so
 *  it's mounted ahead of the first translation on the auth screens, the app
 *  shell, and the public boards — when a locale is added to `i18n/config.ts`,
 *  the picker appears at those mount points with no further code change.
 *  Selection writes the locale cookie and refreshes the server render.
 *
 *  The single-locale guard lives in a hookless wrapper on purpose: while
 *  inert, mounting it must not require a router/intl context (pages test
 *  without one). */
export function LocaleSwitcher(props: { className?: string }) {
  if (LOCALES.length < 2) return null;
  return <LocaleSwitcherSelect {...props} />;
}

/** Exported for tests — via `LocaleSwitcher` it's unreachable until a second
 *  locale ships, and its behavior must not first run in production. */
export function LocaleSwitcherSelect({ className }: { className?: string }) {
  const router = useRouter();
  const locale = useLocale();
  const t = useTranslations("common");
  return (
    <label className={className}>
      <span className="sr-only">{t("language")}</span>
      <Select
        value={locale}
        onChange={(e) => {
          setStoredLocale(e.target.value as Locale);
          router.refresh();
        }}
        className="h-8 w-auto text-xs"
      >
        {LOCALES.map((l) => (
          <option key={l} value={l}>
            {LOCALE_LABELS[l]}
          </option>
        ))}
      </Select>
    </label>
  );
}
