import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { AddSectionModal } from "@/components/dashboard/add-section-modal";
import { type LayoutEntry, widgetsForAudience } from "@/lib/dashboard/registry";

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
    // New manager sections (#332) surface in the catalog.
    expect(screen.getByText("Unsolved challenges")).toBeInTheDocument();
    expect(screen.getByText("Instance health")).toBeInTheDocument();
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
    // Derive from the registry so this stays correct as manager sections grow.
    const present: LayoutEntry[] = widgetsForAudience("manager").map((w, i) => ({
      widgetId: w.id,
      x: 0,
      y: i,
      w: w.defaultSize.w,
      h: w.defaultSize.h,
    }));
    renderWithIntl(
      <AddSectionModal audience="manager" present={present} onAdd={vi.fn()} />,
    );
    openModal();
    expect(
      screen.getByText(/every available section is already on your dashboard/i),
    ).toBeInTheDocument();
  });
});
