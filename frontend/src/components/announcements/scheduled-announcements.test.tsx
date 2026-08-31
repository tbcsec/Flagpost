import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { ScheduledAnnouncements } from "@/components/announcements/scheduled-announcements";

// Drive the component off mocked domain hooks (#349): the list, plus the two
// mutations the management row wires up.
const mockScheduled = vi.fn();
const mockUpdate = vi.fn();
const mockRemove = vi.fn();
vi.mock("@/lib/hooks/use-announcements", () => ({
  useScheduledAnnouncements: (...args: unknown[]) => mockScheduled(...args),
  useUpdateAnnouncement: () => ({ mutate: mockUpdate, isPending: false }),
  useDeleteAnnouncement: () => ({ mutate: mockRemove, isPending: false }),
}));
vi.mock("@/components/ui/confirm", () => ({ useConfirm: () => async () => true }));
vi.mock("@/stores/toast", () => ({ toast: vi.fn() }));

function scheduled(id: string, title = `Draft ${id}`) {
  return {
    id,
    competition_id: "comp-1",
    title,
    body: "Body",
    severity: "info",
    audience_type: "all",
    audience_ids: [],
    created_at: new Date("2026-01-01T00:00:00Z").toISOString(),
    hidden: true,
    publish_at: new Date("2026-06-01T12:00:00Z").toISOString(),
  };
}

describe("ScheduledAnnouncements", () => {
  afterEach(() => vi.clearAllMocks());

  it("renders nothing when there are no scheduled drafts", () => {
    mockScheduled.mockReturnValue({ data: [] });
    const { container } = renderWithIntl(
      <ScheduledAnnouncements competitionId="comp-1" />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("lists each scheduled draft with its management controls", () => {
    mockScheduled.mockReturnValue({ data: [scheduled("a1")] });
    renderWithIntl(<ScheduledAnnouncements competitionId="comp-1" />);
    expect(screen.getByText("Scheduled announcements")).toBeInTheDocument();
    expect(screen.getByText("Draft a1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publish now" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("publishes now by clearing the schedule (publish_at: null)", () => {
    mockScheduled.mockReturnValue({ data: [scheduled("a1")] });
    renderWithIntl(<ScheduledAnnouncements competitionId="comp-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Publish now" }));
    expect(mockUpdate).toHaveBeenCalledTimes(1);
    expect(mockUpdate.mock.calls[0][0]).toEqual({
      id: "a1",
      patch: { publish_at: null },
    });
  });
});
