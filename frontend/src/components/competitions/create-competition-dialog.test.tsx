import { fireEvent, screen, within } from "@testing-library/react";
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

vi.mock("@/lib/hooks/use-modules", () => ({
  useModuleCatalog: () => ({
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

const MODULE_LABELS = [
  "AI Assistants",
  "Analytics",
  "Automations",
  "Certificates",
  "Feedback & Surveys",
];

function openDialog() {
  renderWithIntl(<CreateCompetitionDialog />);
  fireEvent.click(screen.getByRole("button", { name: "New competition" }));
}

/** The Enable/Disable button in a module's row, found by the module name. */
function moduleButton(name: string) {
  const row = screen.getByText(name).closest("li");
  if (!row) throw new Error(`no row for module ${name}`);
  return within(row).getByRole("button");
}

afterEach(() => {
  mockMutate.mockClear();
  vi.restoreAllMocks();
});

describe("CreateCompetitionDialog", () => {
  it("captures scoreboard and schedule, and lists modules on-by-default with descriptions", () => {
    openDialog();
    expect(screen.getByLabelText("Public scoreboard")).not.toBeChecked();
    expect(screen.getByLabelText("Starts (optional)")).toBeInTheDocument();
    expect(screen.getByLabelText("Ends (optional)")).toBeInTheDocument();
    // Each optional module renders its description and an on-by-default row whose
    // button offers to Disable it.
    for (const label of MODULE_LABELS) {
      expect(moduleButton(label)).toHaveTextContent("Disable");
    }
    expect(screen.getByText("Engagement dashboards.")).toBeInTheDocument();
  });

  it("turning a module off flips its button and sends it as disabled_modules", () => {
    openDialog();
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Lean CTF" },
    });
    fireEvent.click(moduleButton("Analytics")); // Disable
    fireEvent.click(moduleButton("Feedback & Surveys")); // Disable
    // The toggled row now offers to re-enable.
    expect(moduleButton("Analytics")).toHaveTextContent("Enable");
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
});
