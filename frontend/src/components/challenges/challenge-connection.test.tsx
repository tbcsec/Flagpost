import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { ChallengeConnection } from "@/components/challenges/challenge-connection";

const writeText = vi.fn(() => Promise.resolve());
vi.stubGlobal("navigator", { clipboard: { writeText } });

const mockToast = vi.fn();
vi.mock("@/stores/toast", () => ({ toast: (...args: unknown[]) => mockToast(...args) }));

afterEach(() => {
  writeText.mockClear();
  writeText.mockImplementation(() => Promise.resolve());
  mockToast.mockClear();
});

describe("ChallengeConnection (#262)", () => {
  it("renders a non-URL value as inert monospace text, never a link", () => {
    renderWithIntl(<ChallengeConnection value="nc box.example.com 1337" />);
    expect(screen.getByText("nc box.example.com 1337")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("linkifies an http(s) URL, opening safely in a new tab", () => {
    renderWithIntl(<ChallengeConnection value="https://box.example.com/pwn" />);
    const link = screen.getByRole("link", { name: "https://box.example.com/pwn" });
    expect(link).toHaveAttribute("href", "https://box.example.com/pwn");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it.each([
    ["javascript:alert(1)"],
    ["data:text/html,<script>alert(1)</script>"],
    ["httpfoo://nope"],
    ["http://"],
  ])("never linkifies %s", (value) => {
    renderWithIntl(<ChallengeConnection value={value} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText(value)).toBeInTheDocument();
  });

  it("copies the raw value and confirms, then reverts", async () => {
    vi.useFakeTimers();
    renderWithIntl(<ChallengeConnection value="nc box.example.com 1337" />);
    // act + flushed microtasks so the post-await setState lands inside act().
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    });
    expect(writeText).toHaveBeenCalledWith("nc box.example.com 1337");
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
    // Reverts after the 2s window.
    act(() => void vi.advanceTimersByTime(2000));
    expect(screen.getByRole("button", { name: "Copy" })).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("toasts instead of throwing when the clipboard is unavailable", async () => {
    writeText.mockImplementation(() => Promise.reject(new Error("denied")));
    renderWithIntl(<ChallengeConnection value="nc box.example.com 1337" />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    });
    expect(mockToast).toHaveBeenCalled();
    expect(mockToast.mock.calls[0][1]).toMatchObject({ variant: "destructive" });
    // Still shows "Copy" — a failed copy must not claim success.
    expect(screen.getByRole("button", { name: "Copy" })).toBeInTheDocument();
  });
});
