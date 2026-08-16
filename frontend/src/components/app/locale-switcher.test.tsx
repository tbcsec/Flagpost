import { describe, expect, it, vi } from "vitest";

import { LocaleSwitcher } from "@/components/app/locale-switcher";
import { setStoredLocale } from "@/i18n/client";
import { LOCALE_COOKIE } from "@/i18n/config";
import { renderWithIntl } from "@/test/intl";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

describe("LocaleSwitcher", () => {
  // While only English ships, the picker must stay invisible everywhere it's
  // mounted — it appears by itself once a second locale lands in i18n/config.
  it("renders nothing while only one locale ships", () => {
    const { container } = renderWithIntl(<LocaleSwitcher />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("setStoredLocale", () => {
  it("persists the choice as a site-wide cookie", () => {
    setStoredLocale("en");
    expect(document.cookie).toContain(`${LOCALE_COOKIE}=en`);
  });
});
