import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CreateCompetitionDialog } from "@/components/competitions/create-competition-dialog";
import { renderWithIntl } from "@/test/intl";

const mockMutate = vi.fn();
vi.mock("@/lib/hooks/use-competitions", () => ({
  useCreateCompetition: () => ({
    mutate: mockMutate,
    isPending: false,
    isError: false,
    error: null,
    reset: vi.fn(),
  }),
}));

let catalogLoading = false;
vi.mock("@/lib/hooks/use-modules", () => ({
  useModuleCatalog: () => (catalogLoading ? { data: undefined, isLoading: true } : {
    data: [
      { id: "ai", name: "AI Assistants", description: "A read-only assistant." },
      { id: "analytics", name: "Analytics", description: "Engagement dashboards." },
      { id: "automations", name: "Automations", description: "Event-driven actions." },
      { id: "certificates", name: "Certificates", description: "Shareable certificates." },
      { id: "feedback", name: "Feedback & Surveys", description: "Surveys and ratings." },
    ],
    isLoading: false,
  }),
}));

// The tiles' names come from the UI's module copy, not the manifests above.
const MODULE_LABELS = ["AI assistants", "Analytics", "Automations", "Certificates", "Feedback"];

function openDialog() {
  renderWithIntl(<CreateCompetitionDialog />);
  fireEvent.click(screen.getByRole("button", { name: "New competition" }));
}

/** A module tile's on/off switch, labelled by the module's name (#502). */
function moduleSwitch(name: string) {
  return screen.getByRole("switch", { name });
}

afterEach(() => {
  catalogLoading = false;
  mockMutate.mockClear();
  vi.restoreAllMocks();
});

describe("CreateCompetitionDialog", () => {
  it("captures scoreboard and schedule, and lists modules on-by-default with descriptions", () => {
    openDialog();
    expect(screen.getByLabelText("Public scoreboard")).not.toBeChecked();
    expect(screen.getByLabelText("Starts (optional)")).toBeInTheDocument();
    expect(screen.getByLabelText("Ends (optional)")).toBeInTheDocument();
    // Each optional module is a tile, on by default, with the UI's own
    // plain-language description rather than the manifest's.
    for (const label of MODULE_LABELS) {
      expect(moduleSwitch(label)).toHaveAttribute("aria-checked", "true");
    }
    expect(
      screen.getByText("Solve rates, completion and timing per challenge and team, for organisers."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Engagement dashboards.")).toBeNull();
  });

  it("turning a module off flips its button and sends it as disabled_modules", () => {
    openDialog();
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Lean CTF" },
    });
    fireEvent.click(moduleSwitch("Analytics")); // off
    fireEvent.click(moduleSwitch("Feedback")); // off
    expect(moduleSwitch("Analytics")).toHaveAttribute("aria-checked", "false");
    fireEvent.click(screen.getByLabelText("Public scoreboard")); // enable
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(mockMutate).toHaveBeenCalledTimes(1);
    const payload = mockMutate.mock.calls[0][0];
    expect(payload.name).toBe("Lean CTF");
    expect(payload.public_scoreboard).toBe(true);
    expect(new Set(payload.disabled_modules)).toEqual(
      new Set(["analytics", "feedback"]),
    );
  });

  it("says the modules are loading until the catalog arrives", () => {
    catalogLoading = true;
    openDialog();
    expect(screen.getByText("Loading modules…")).toBeInTheDocument();
    expect(screen.queryByRole("switch")).toBeNull();
  });
});
