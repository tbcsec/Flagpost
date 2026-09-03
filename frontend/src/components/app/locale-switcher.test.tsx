import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  LocaleSwitcher,
  LocaleSwitcherSelect,
} from "@/components/app/locale-switcher";
import { setStoredLocale } from "@/i18n/client";
import { LOCALE_COOKIE } from "@/i18n/config";
import { renderWithIntl } from "@/test/intl";

const mockRefresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: mockRefresh }),
}));

afterEach(() => {
  mockRefresh.mockClear();
  vi.restoreAllMocks();
});

describe("LocaleSwitcher", () => {
  // en/fr/es/pl now ship (ADR-0029), so the wrapper is live: it delegates to the
  // picker at every mount point (auth screens, app shell, public boards). The
  // single-locale guard (`LOCALES.length < 2 → null`) stays in the code for a
  // hypothetical one-language build; it simply no longer fires with this config.
  it("renders the language picker now that more than one locale ships", () => {
    renderWithIntl(<LocaleSwitcher />);
    expect(screen.getByLabelText("Language")).toBeInTheDocument();
  });
});

describe("LocaleSwitcherSelect", () => {
  // Unreachable via LocaleSwitcher until a second locale ships — tested
  // directly so its first real run isn't in production (see export comment).
  it("lists the shipped locales by their endonym", () => {
    renderWithIntl(<LocaleSwitcherSelect />);
    expect(screen.getByLabelText("Language")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "English" })).toBeInTheDocument();
  });

  it("persists a selection to the locale cookie, then refreshes the server render", () => {
    const cookieWrites: string[] = [];
    vi.spyOn(document, "cookie", "set").mockImplementation((value) => {
      cookieWrites.push(value);
    });
    renderWithIntl(<LocaleSwitcherSelect />);
    fireEvent.change(screen.getByLabelText("Language"), {
      target: { value: "en" },
    });
    expect(cookieWrites).toHaveLength(1);
    expect(cookieWrites[0]).toContain(`${LOCALE_COOKIE}=en`);
    expect(mockRefresh).toHaveBeenCalledTimes(1);
  });
});

describe("setStoredLocale", () => {
  it("writes a site-wide, year-long, lax cookie", () => {
    // jsdom's document.cookie getter never exposes attributes (per spec), so
    // pin them at the setter — path=/ is what makes a choice made on /login
    // apply to every route.
    const cookieWrites: string[] = [];
    vi.spyOn(document, "cookie", "set").mockImplementation((value) => {
      cookieWrites.push(value);
    });
    setStoredLocale("en");
    expect(cookieWrites[0]).toContain(`${LOCALE_COOKIE}=en`);
    expect(cookieWrites[0]).toContain("path=/");
    expect(cookieWrites[0]).toContain(`max-age=${60 * 60 * 24 * 365}`);
    expect(cookieWrites[0]).toContain("SameSite=Lax");
  });
});
