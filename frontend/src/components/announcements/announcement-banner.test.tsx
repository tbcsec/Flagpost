import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AnnouncementBanner } from "@/components/announcements/announcement-banner";

// The banner only reads the newest announcement and the active competition —
// mock both domain inputs so the tests drive pure banner behaviour (#19).
const mockUseAnnouncements = vi.fn();
vi.mock("@/lib/hooks/use-announcements", () => ({
  useAnnouncements: (...args: unknown[]) => mockUseAnnouncements(...args),
}));
vi.mock("@/stores/auth", () => ({
  useAuthStore: (selector: (s: { activeCompetitionId: string }) => unknown) =>
    selector({ activeCompetitionId: "comp-1" }),
}));

function announcement(id: string, title = `Title ${id}`) {
  return { id, title, body: "Body", created_at: new Date().toISOString() };
}

describe("AnnouncementBanner", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("shows the newest announcement", () => {
    mockUseAnnouncements.mockReturnValue({ data: [announcement("a1")] });
    render(<AnnouncementBanner />);
    expect(screen.getByText("Title a1")).toBeInTheDocument();
  });

  it("auto-dismisses after the dwell time", () => {
    mockUseAnnouncements.mockReturnValue({ data: [announcement("a1")] });
    render(<AnnouncementBanner />);
    act(() => vi.advanceTimersByTime(30_000));
    expect(screen.queryByText("Title a1")).not.toBeInTheDocument();
  });

  it("re-shows for a newer announcement after the previous auto-dismissed", () => {
    mockUseAnnouncements.mockReturnValue({ data: [announcement("a1")] });
    const { rerender } = render(<AnnouncementBanner />);
    act(() => vi.advanceTimersByTime(30_000)); // a1 dismissed

    // A newer announcement arrives (prepended by the WS cache update).
    mockUseAnnouncements.mockReturnValue({
      data: [announcement("a2"), announcement("a1")],
    });
    rerender(<AnnouncementBanner />);
    expect(screen.getByText("Title a2")).toBeInTheDocument();

    // The new arrival gets its own full dwell, then goes too.
    act(() => vi.advanceTimersByTime(30_000));
    expect(screen.queryByText("Title a2")).not.toBeInTheDocument();
  });

  it("manual dismissal still works and doesn't hide a later announcement", () => {
    mockUseAnnouncements.mockReturnValue({ data: [announcement("a1")] });
    const { rerender } = render(<AnnouncementBanner />);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss announcement" }));
    expect(screen.queryByText("Title a1")).not.toBeInTheDocument();

    mockUseAnnouncements.mockReturnValue({
      data: [announcement("a2"), announcement("a1")],
    });
    rerender(<AnnouncementBanner />);
    expect(screen.getByText("Title a2")).toBeInTheDocument();
  });
});
