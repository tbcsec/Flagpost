import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

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

function announcement(id: string, title = `Title ${id}`, severity = "info") {
  return {
    id,
    title,
    body: "Body",
    severity,
    audience_type: "all",
    audience_ids: [],
    created_at: new Date().toISOString(),
  };
}

describe("AnnouncementBanner", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("shows the newest announcement", () => {
    mockUseAnnouncements.mockReturnValue({ data: [announcement("a1")] });
    renderWithIntl(<AnnouncementBanner />);
    expect(screen.getByText("Title a1")).toBeInTheDocument();
  });

  it("auto-dismisses after the dwell time", () => {
    mockUseAnnouncements.mockReturnValue({ data: [announcement("a1")] });
    renderWithIntl(<AnnouncementBanner />);
    act(() => vi.advanceTimersByTime(30_000));
    expect(screen.queryByText("Title a1")).not.toBeInTheDocument();
  });

  it("re-shows for a newer announcement after the previous auto-dismissed", () => {
    mockUseAnnouncements.mockReturnValue({ data: [announcement("a1")] });
    const { rerender } = renderWithIntl(<AnnouncementBanner />);
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

  it("keeps a critical announcement on screen until dismissed (#40)", () => {
    mockUseAnnouncements.mockReturnValue({
      data: [announcement("a1", "Evacuate", "critical")],
    });
    renderWithIntl(<AnnouncementBanner />);
    // Far past any ordinary dwell — a self-dismissing "critical" would
    // undercut the whole tier.
    act(() => vi.advanceTimersByTime(10 * 60_000));
    expect(screen.getByText("Evacuate")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss announcement" }));
    expect(screen.queryByText("Evacuate")).not.toBeInTheDocument();
  });

  it("labels severity and marks a critical announcement as an alert", () => {
    mockUseAnnouncements.mockReturnValue({
      data: [announcement("a1", "Heads up", "warning")],
    });
    const { rerender } = renderWithIntl(<AnnouncementBanner />);
    expect(screen.getByText("Important")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();

    mockUseAnnouncements.mockReturnValue({
      data: [announcement("a2", "Evacuate", "critical")],
    });
    rerender(<AnnouncementBanner />);
    expect(screen.getByText("Urgent")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("manual dismissal still works and doesn't hide a later announcement", () => {
    mockUseAnnouncements.mockReturnValue({ data: [announcement("a1")] });
    const { rerender } = renderWithIntl(<AnnouncementBanner />);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss announcement" }));
    expect(screen.queryByText("Title a1")).not.toBeInTheDocument();

    mockUseAnnouncements.mockReturnValue({
      data: [announcement("a2"), announcement("a1")],
    });
    rerender(<AnnouncementBanner />);
    expect(screen.getByText("Title a2")).toBeInTheDocument();
  });
});
