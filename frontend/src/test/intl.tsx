import { render, type RenderOptions } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";

import { DEFAULT_LOCALE } from "@/i18n/config";

import en from "../../messages/en.json";

// Test-side stand-in for the NextIntlClientProvider the root layout mounts:
// components extracted to next-intl (ADR-0029) throw outside an intl context.
// Always the English source messages — tests assert user-visible English text.
export function IntlProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextIntlClientProvider locale={DEFAULT_LOCALE} messages={en} timeZone="UTC">
      {children}
    </NextIntlClientProvider>
  );
}

/** `render` with the intl context pre-wrapped. Tests that need their own
 *  wrapper (e.g. a QueryClientProvider) compose `IntlProvider` inside it. */
export function renderWithIntl(
  ui: React.ReactElement,
  options?: Omit<RenderOptions, "wrapper">,
) {
  return render(ui, { wrapper: IntlProvider, ...options });
}
