import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { DeploymentSection } from "@/components/challenges/deployment-section";

// The flag-mode authoring UI (#266 Phase 2a, ADR-0036 §3): a Select that reveals
// a template field in unique mode, client-side <random> validation, and the
// payload it sends to the upsert hook.

const mockUpsert = vi.fn();

vi.mock("@/lib/hooks/use-instances", () => ({
  useChallengeDeployment: () => ({ data: null, isLoading: false }),
  useUpsertChallengeDeployment: () => ({ mutate: mockUpsert, isPending: false }),
  useDeleteChallengeDeployment: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/components/ui/confirm", () => ({
  useConfirm: () => () => Promise.resolve(true),
}));

const mockToast = vi.fn();
vi.mock("@/stores/toast", () => ({ toast: (...args: unknown[]) => mockToast(...args) }));

afterEach(() => {
  mockUpsert.mockClear();
  mockToast.mockClear();
});

function render() {
  renderWithIntl(<DeploymentSection competitionId="c1" challengeId="ch1" />);
  // A minimally valid docker spec with no ports gate (exposure "none").
  fireEvent.change(screen.getByLabelText("Container image"), {
    target: { value: "img:1" },
  });
  fireEvent.change(screen.getByLabelText("Exposure"), { target: { value: "none" } });
}

function setFlagMode(value: string) {
  fireEvent.change(screen.getByLabelText("Flag mode"), { target: { value } });
}

const save = () => fireEvent.click(screen.getByRole("button", { name: /set deployment/i }));

describe("DeploymentSection flag mode", () => {
  it("shows the template field only in unique mode", () => {
    render();
    expect(screen.queryByLabelText("Flag template")).toBeNull();
    setFlagMode("unique_per_instance");
    expect(screen.getByLabelText("Flag template")).toBeInTheDocument();
  });

  it("blocks save and warns when the unique template lacks <random>", () => {
    render();
    setFlagMode("unique_per_instance");
    fireEvent.change(screen.getByLabelText("Flag template"), {
      target: { value: "flag{fixed}" },
    });
    save();
    expect(mockUpsert).not.toHaveBeenCalled();
    expect(mockToast).toHaveBeenCalled();
  });

  it("sends flag_mode + trimmed flag_template in unique mode", () => {
    render();
    setFlagMode("unique_per_instance");
    fireEvent.change(screen.getByLabelText("Flag template"), {
      target: { value: "  flag{a-<random>}  " },
    });
    save();
    expect(mockUpsert).toHaveBeenCalledTimes(1);
    const payload = mockUpsert.mock.calls[0][0];
    expect(payload.flag_mode).toBe("unique_per_instance");
    expect(payload.flag_template).toBe("flag{a-<random>}");
  });

  it("defaults to static mode with a null template", () => {
    render();
    save();
    expect(mockUpsert).toHaveBeenCalledTimes(1);
    const payload = mockUpsert.mock.calls[0][0];
    expect(payload.flag_mode).toBe("static");
    expect(payload.flag_template).toBeNull();
  });
});
