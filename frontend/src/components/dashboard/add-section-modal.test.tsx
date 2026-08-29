import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { AddSectionModal } from "@/components/dashboard/add-section-modal";
import type { LayoutEntry } from "@/lib/dashboard/registry";

// Add-section catalog modal (#330): the audience-scoped card list, add fires
// onAdd(widgetId), already-present sections are excluded, and an empty state
// shows when everything eligible is already on the dashboard.

const openModal = () =>
  fireEvent.click(screen.getByRole("button", { name: "Add section" }));

describe("AddSectionModal", () => {
  it("lists manager-eligible sections and excludes competitor-personal ones", () => {
    renderWithIntl(<AddSectionModal audience="manager" present={[]} onAdd={vi.fn()} />);
    openModal();
    expect(screen.getByText("At a glance")).toBeInTheDocument(); // stats
    expect(screen.getByText("Challenge health")).toBeInTheDocument();
    expect(screen.getByText("Support queue")).toBeInTheDocument();
    // Competitor-personal sections must not surface on the manager catalog.
    expect(screen.queryByText("Your solves")).not.toBeInTheDocument();
    expect(screen.queryByText("Your standing")).not.toBeInTheDocument();
  });

  it("excludes sections already on the dashboard and adds by id", () => {
    const onAdd = vi.fn();
    const present: LayoutEntry[] = [{ widgetId: "stats", x: 0, y: 0, w: 12, h: 2 }];
    renderWithIntl(
      <AddSectionModal audience="manager" present={present} onAdd={onAdd} />,
    );
    openModal();
    expect(screen.queryByText("At a glance")).not.toBeInTheDocument(); // already present
    fireEvent.click(screen.getByRole("button", { name: "Add Support queue" }));
    expect(onAdd).toHaveBeenCalledWith("support-queue");
  });

  it("shows the empty state when every eligible section is present", () => {
    const present: LayoutEntry[] = [
      { widgetId: "stats", x: 0, y: 0, w: 12, h: 2 },
      { widgetId: "activity", x: 0, y: 2, w: 6, h: 5 },
      { widgetId: "announcements", x: 6, y: 2, w: 6, h: 5 },
      { widgetId: "challenge-health", x: 0, y: 7, w: 6, h: 5 },
      { widgetId: "support-queue", x: 6, y: 7, w: 6, h: 5 },
    ];
    renderWithIntl(
      <AddSectionModal audience="manager" present={present} onAdd={vi.fn()} />,
    );
    openModal();
    expect(
      screen.getByText(/every available section is already on your dashboard/i),
    ).toBeInTheDocument();
  });
});
