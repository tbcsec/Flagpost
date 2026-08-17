import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguageMenu } from "@/components/app/language-menu";
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

describe("LanguageMenu", () => {
  it("opens to list the shipped locales by their endonym", () => {
    renderWithIntl(<LanguageMenu />);
    // Collapsed by default — the endonyms appear only once the globe is opened.
    expect(screen.queryByText("Français")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Language" }));
    expect(screen.getByText("English")).toBeInTheDocument();
    expect(screen.getByText("Français")).toBeInTheDocument();
    expect(screen.getByText("Español")).toBeInTheDocument();
    expect(screen.getByText("Polski")).toBeInTheDocument();
  });

  it("persists the chosen locale to the cookie, then refreshes the server render", () => {
    const cookieWrites: string[] = [];
    vi.spyOn(document, "cookie", "set").mockImplementation((value) => {
      cookieWrites.push(value);
    });
    renderWithIntl(<LanguageMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Language" }));
    fireEvent.click(screen.getByText("Français"));
    expect(cookieWrites).toHaveLength(1);
    expect(cookieWrites[0]).toContain(`${LOCALE_COOKIE}=fr`);
    expect(mockRefresh).toHaveBeenCalledTimes(1);
  });
});
