import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";
import type { JudgeLanguage, JudgeSettings } from "@/lib/types";

// Admin → Site settings → Code judge (#446/#447). The judge ships inert, so the
// enable invariant (endpoint + an enabled language) is mirrored client-side;
// language commands are argv lists entered one argument per line.

const mockUpdateSettings = vi.fn();
const mockCreate = vi.fn();
const mockUpdateLanguage = vi.fn();
const mockToast = vi.fn();
let settings: JudgeSettings;
let languages: JudgeLanguage[];

vi.mock("@/lib/hooks/use-judge", () => ({
  useJudgeSettings: () => ({ data: settings, isLoading: false }),
  useJudgeLanguages: () => ({ data: languages, isLoading: false }),
  useUpdateJudgeSettings: () => ({ mutate: mockUpdateSettings, isPending: false }),
  useCreateJudgeLanguage: () => ({ mutate: mockCreate, isPending: false }),
  useUpdateJudgeLanguage: () => ({ mutate: mockUpdateLanguage, isPending: false }),
  useDeleteJudgeLanguage: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/stores/toast", () => ({ toast: (...args: unknown[]) => mockToast(...args) }));

import { JudgeSettingsPanel } from "./judge-settings-panel";

function baseSettings(over: Partial<JudgeSettings> = {}): JudgeSettings {
  return {
    enabled: false,
    executor: "docker",
    endpoint_url: null,
    max_concurrent_judgings: 1,
    default_time_limit_ms: 2000,
    default_memory_limit_mb: 256,
    default_output_limit_kb: 8192,
    ...over,
  };
}

const python: JudgeLanguage = {
  id: "lang-1",
  key: "python3",
  name: "Python 3",
  image_ref: "python:3.13-slim",
  source_filename: "solution.py",
  compile_command: null,
  run_command: ["python3", "{source}"],
  time_multiplier: 2,
  enabled: true,
};

describe("JudgeSettingsPanel", () => {
  beforeEach(() => {
    mockUpdateSettings.mockClear();
    mockCreate.mockClear();
    mockUpdateLanguage.mockClear();
    mockToast.mockClear();
  });

  it("refuses to enable the judge with no enabled language", () => {
    settings = baseSettings({ endpoint_url: "http://socket-proxy:2375" });
    languages = [];
    renderWithIntl(<JudgeSettingsPanel />);

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "on" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(mockUpdateSettings).not.toHaveBeenCalled();
    expect(mockToast).toHaveBeenCalledWith(
      "Add and enable at least one language before enabling the judge.",
      expect.anything(),
    );
  });

  it("saves the settings once an endpoint and a language exist", () => {
    settings = baseSettings();
    languages = [python];
    renderWithIntl(<JudgeSettingsPanel />);

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "on" } });
    fireEvent.change(screen.getByLabelText("Container endpoint"), {
      target: { value: "http://socket-proxy:2375" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(mockUpdateSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        enabled: true,
        endpoint_url: "http://socket-proxy:2375",
        max_concurrent_judgings: 1,
      }),
      expect.anything(),
    );
  });

  it("sends commands as one argv entry per line, and an empty compile box as null", () => {
    settings = baseSettings();
    languages = [];
    renderWithIntl(<JudgeSettingsPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Add language" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Python 3" } });
    fireEvent.change(screen.getByLabelText("Key"), { target: { value: "python3" } });
    fireEvent.change(screen.getByLabelText("Container image"), {
      target: { value: "python:3.13-slim" },
    });
    fireEvent.change(screen.getByLabelText("Source filename"), {
      target: { value: "solution.py" },
    });
    // An argument containing a space stays one argument; blank lines drop.
    fireEvent.change(screen.getByLabelText("Run command"), {
      target: { value: "python3\n\n-X utf8\n{source}\n" },
    });
    fireEvent.submit(screen.getByLabelText("Run command").closest("form")!);

    expect(mockCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        key: "python3",
        compile_command: null,
        run_command: ["python3", "-X utf8", "{source}"],
      }),
      expect.anything(),
    );
  });

  it("locks the key when editing, and never sends it", () => {
    settings = baseSettings();
    languages = [python];
    renderWithIntl(<JudgeSettingsPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByLabelText("Key")).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Python" } });
    fireEvent.submit(screen.getByLabelText("Run command").closest("form")!);

    expect(mockUpdateLanguage).toHaveBeenCalledTimes(1);
    const [{ id, input }] = mockUpdateLanguage.mock.calls[0];
    expect(id).toBe("lang-1");
    expect(input).not.toHaveProperty("key");
    expect(input.name).toBe("Python");
  });

  it("shows the command placeholders literally rather than as ICU arguments", () => {
    // {source}/{work} would otherwise be parsed as ICU arguments and fail.
    settings = baseSettings();
    languages = [];
    renderWithIntl(<JudgeSettingsPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Add language" }));
    expect(screen.getByText("{source}")).toBeInTheDocument();
    expect(screen.getByText("{work}")).toBeInTheDocument();
  });
});
