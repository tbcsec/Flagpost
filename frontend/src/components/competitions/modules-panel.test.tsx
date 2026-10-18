import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ModulesPanel } from "@/components/competitions/modules-panel";
import type { ModuleState } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";

// Settings → Modules as tiles (#502): optional modules first, the always-on
// ones collapsed below, toggles through the existing endpoint.

let canManage = true;
let loading = false;
let pending = false;
let modules: ModuleState[] = [];
const mutate = vi.fn();
const toast = vi.fn();
vi.mock("@/lib/hooks/use-permissions", () => ({
  useAccess: () => ({ has: (p: string) => p === "manage_modules" && canManage }),
}));

function mod(id: string, name: string, overrides: Partial<ModuleState> = {}): ModuleState {
  return {
    id,
    name,
    version: "1.0.0",
    enabled: true,
    required_core: false,
    description: "",
    needs_setup: false,
    ...overrides,
  };
}

vi.mock("@/lib/hooks/use-modules", () => ({
  useModules: () => ({ isLoading: loading, data: loading ? undefined : modules }),
  useToggleModule: () => ({ mutate, isPending: pending }),
}));
vi.mock("@/stores/toast", () => ({ toast: (...a: unknown[]) => toast(...a) }));

beforeEach(() => {
  canManage = true;
  loading = false;
  pending = false;
  modules = [
    mod("feedback", "Feedback & Surveys"),
    mod("judge", "Code Judge", { enabled: false, needs_setup: true }),
    mod("challenges", "Challenges", { required_core: true }),
    mod("scoring", "Scoring & Scoreboard", { required_core: true }),
  ];
  mutate.mockReset();
  toast.mockReset();
});

describe("ModulesPanel", () => {
  it("shows the optional modules as tiles, with the always-on ones tucked away", () => {
    renderWithIntl(<ModulesPanel competitionId="c1" />);
    expect(screen.getByRole("switch", { name: "Feedback" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("switch", { name: "Code judge" })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText(/Needs site setup/)).toBeInTheDocument();
    // Core modules: hidden until asked for, then shown always on.
    expect(screen.queryByText("Scoreboard")).toBeNull();
    const fold = screen.getByRole("button", { name: "Show the 2 always-on modules" });
    expect(fold).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(fold);
    expect(screen.getByText("Scoreboard")).toBeInTheDocument();
    expect(screen.getAllByText("Always on")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Hide the always-on modules" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("switches a module through the API and confirms by its UI name", () => {
    mutate.mockImplementation((_vars, { onSuccess }) => onSuccess());
    renderWithIntl(<ModulesPanel competitionId="c1" />);
    fireEvent.click(screen.getByRole("switch", { name: "Code judge" }));
    expect(mutate.mock.calls[0][0]).toEqual({ moduleId: "judge", enabled: true });
    expect(toast).toHaveBeenCalledWith("Code judge enabled", { variant: "success" });
  });

  it("is hidden without manage_modules", () => {
    canManage = false;
    const { container } = renderWithIntl(<ModulesPanel competitionId="c1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("confirms a switch-off, and reports a failure", () => {
    mutate.mockImplementationOnce((_vars, { onSuccess }) => onSuccess());
    renderWithIntl(<ModulesPanel competitionId="c1" />);
    fireEvent.click(screen.getByRole("switch", { name: "Feedback" }));
    expect(mutate.mock.calls[0][0]).toEqual({ moduleId: "feedback", enabled: false });
    expect(toast).toHaveBeenLastCalledWith("Feedback disabled", { variant: "success" });

    mutate.mockImplementationOnce((_vars, { onError }) => onError(new Error("Nope")));
    fireEvent.click(screen.getByRole("switch", { name: "Feedback" }));
    expect(toast).toHaveBeenLastCalledWith("Couldn't update module", {
      description: "Nope",
      variant: "destructive",
    });
  });

  it("holds every switch while a change is in flight", () => {
    pending = true;
    renderWithIntl(<ModulesPanel competitionId="c1" />);
    for (const toggle of screen.getAllByRole("switch")) expect(toggle).toBeDisabled();
  });

  it("shows a placeholder while loading, and no empty card", () => {
    loading = true;
    const { container, unmount } = renderWithIntl(<ModulesPanel competitionId="c1" />);
    expect(screen.queryByRole("switch")).toBeNull();
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
    unmount();
    loading = false;
    modules = [mod("challenges", "Challenges", { required_core: true })];
    renderWithIntl(<ModulesPanel competitionId="c1" />);
    expect(screen.queryByText("Optional modules")).toBeNull();
    expect(screen.getByRole("button", { name: "Show the always-on module" })).toBeInTheDocument();
  });
});
