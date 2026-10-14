import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";
import type { JudgeLanguage, JudgeLanguagePreset, JudgeSettings } from "@/lib/types";

// Admin → Site settings → Code judge (#446/#447). Built-in languages are ticked
// on from presets; custom languages are the advanced path, with argv commands
// entered one argument per line. The judge ships inert, so the enable invariant
// (endpoint + an enabled language) is mirrored client-side.

const mockUpdateSettings = vi.fn();
const mockCreate = vi.fn();
const mockUpdateLanguage = vi.fn();
const mockToast = vi.fn();
let settings: JudgeSettings;
let languages: JudgeLanguage[];

const presets: JudgeLanguagePreset[] = [
  {
    key: "python3",
    name: "Python 3",
    image_ref: "python:3.14-slim",
    source_filename: "solution.py",
    compile_command: null,
    run_command: ["python3", "{source}"],
    time_multiplier: 1,
  },
  {
    key: "cpp",
    name: "C++",
    image_ref: "gcc:16",
    source_filename: "main.cpp",
    compile_command: ["g++", "-O2", "-o", "{work}/main", "{source}"],
    run_command: ["{work}/main"],
    time_multiplier: 1,
  },
];

vi.mock("@/lib/hooks/use-judge", () => ({
  useJudgeSettings: () => ({ data: settings, isLoading: false }),
  useJudgeLanguages: () => ({ data: languages, isLoading: false }),
  useJudgeLanguagePresets: () => ({ data: presets, isLoading: false }),
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
    suggested_endpoint_url: "http://socket-proxy:2375",
    ...over,
  };
}

/** The Python preset, as an added (stored) language. */
const addedPython: JudgeLanguage = {
  id: "lang-1",
  key: "python3",
  name: "Python 3",
  image_ref: "python:3.13-slim", // re-pinned by the operator
  source_filename: "solution.py",
  compile_command: null,
  run_command: ["python3", "{source}"],
  time_multiplier: 1,
  enabled: true,
};

describe("JudgeSettingsPanel", () => {
  beforeEach(() => {
    mockUpdateSettings.mockClear();
    mockCreate.mockClear();
    mockUpdateLanguage.mockClear();
    mockToast.mockClear();
  });

  it("prefills the suggested endpoint when none is stored", () => {
    settings = baseSettings({ suggested_endpoint_url: "http://chal-proxy:2375" });
    languages = [];
    renderWithIntl(<JudgeSettingsPanel />);
    expect(screen.getByLabelText("Container endpoint")).toHaveValue("http://chal-proxy:2375");
  });

  it("refuses to enable the judge with no enabled language", () => {
    settings = baseSettings();
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

  it("saves the prefilled endpoint once a language is enabled", () => {
    settings = baseSettings();
    languages = [addedPython];
    renderWithIntl(<JudgeSettingsPanel />);

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "on" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(mockUpdateSettings).toHaveBeenCalledWith(
      expect.objectContaining({ enabled: true, endpoint_url: "http://socket-proxy:2375" }),
      expect.anything(),
    );
  });

  it("ticking a built-in that isn't added yet creates it from the preset", () => {
    settings = baseSettings();
    languages = [];
    renderWithIntl(<JudgeSettingsPanel />);

    fireEvent.click(screen.getByRole("checkbox", { name: /C\+\+/ }));

    expect(mockCreate).toHaveBeenCalledWith(
      expect.objectContaining({ key: "cpp", image_ref: "gcc:16", enabled: true }),
      expect.anything(),
    );
    expect(mockUpdateLanguage).not.toHaveBeenCalled();
  });

  it("unticking an added built-in disables the stored row, keeping its pinned image", () => {
    settings = baseSettings();
    languages = [addedPython];
    renderWithIntl(<JudgeSettingsPanel />);

    // The row shows the operator's pin, not the preset's newer tag.
    expect(screen.getByText("python:3.13-slim")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /Python 3/ }));

    expect(mockUpdateLanguage).toHaveBeenCalledWith(
      { id: "lang-1", input: { enabled: false } },
      expect.anything(),
    );
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it("a custom language's commands go one argv entry per line; empty compile is null", () => {
    settings = baseSettings();
    languages = [];
    renderWithIntl(<JudgeSettingsPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Add custom language" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Python + NumPy" } });
    fireEvent.change(screen.getByLabelText("Key"), { target: { value: "python-numpy" } });
    fireEvent.change(screen.getByLabelText("Container image"), {
      target: { value: "registry.example.org/py-numpy:1" },
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
        key: "python-numpy",
        compile_command: null,
        run_command: ["python3", "-X utf8", "{source}"],
      }),
      expect.anything(),
    );
  });

  it("locks the key when editing, and never sends it", () => {
    settings = baseSettings();
    languages = [addedPython];
    renderWithIntl(<JudgeSettingsPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Edit Python 3" }));
    expect(screen.getByLabelText("Key")).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Container image"), {
      target: { value: "python:3.14-slim" },
    });
    fireEvent.submit(screen.getByLabelText("Run command").closest("form")!);

    expect(mockUpdateLanguage).toHaveBeenCalledTimes(1);
    const [{ id, input }] = mockUpdateLanguage.mock.calls[0];
    expect(id).toBe("lang-1");
    expect(input).not.toHaveProperty("key");
    expect(input.image_ref).toBe("python:3.14-slim");
  });

  it("shows the command placeholders literally rather than as ICU arguments", () => {
    // {source}/{work} would otherwise be parsed as ICU arguments and fail.
    settings = baseSettings();
    languages = [];
    renderWithIntl(<JudgeSettingsPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Add custom language" }));
    expect(screen.getByText("{source}")).toBeInTheDocument();
    expect(screen.getByText("{work}")).toBeInTheDocument();
  });
});
