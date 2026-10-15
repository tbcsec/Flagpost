import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";
import type {
  JudgeCheckResult,
  JudgeLanguage,
  JudgeLanguagePreset,
  JudgeSettings,
} from "@/lib/types";

// Admin → Site settings → Code judge (#446/#447). While the judge is off the
// tab is a guided setup (Connect → Languages → Review & enable) ending in one
// atomic call; once on, a short summary with everything else under Advanced.

type MutateOpts = { onSuccess?: (data?: unknown) => void; onError?: (e: unknown) => void };

const mockUpdateSettings = vi.fn((_input: unknown, opts?: MutateOpts) => opts?.onSuccess?.());
const mockCheck = vi.fn();
const mockApply = vi.fn();
const mockCreate = vi.fn();
const mockUpdateLanguage = vi.fn();
const mockToast = vi.fn();
let settings: JudgeSettings;
let languages: JudgeLanguage[];
let checkResult: JudgeCheckResult;

const presets: JudgeLanguagePreset[] = [
  { key: "python3", name: "Python 3", image_ref: "python:3.14-slim", source_filename: "solution.py", compile_command: null, run_command: ["python3", "{source}"], time_multiplier: 1 },
  { key: "pypy3", name: "PyPy 3", image_ref: "pypy:3.11-slim", source_filename: "solution.py", compile_command: null, run_command: ["pypy3", "{source}"], time_multiplier: 1 },
  { key: "cpp", name: "C++", image_ref: "gcc:16", source_filename: "main.cpp", compile_command: ["g++", "-o", "{work}/main", "{source}"], run_command: ["{work}/main"], time_multiplier: 1 },
  { key: "java", name: "Java", image_ref: "eclipse-temurin:25-jdk", source_filename: "Main.java", compile_command: ["javac", "-d", "{work}", "{source}"], run_command: ["java", "-cp", "{work}", "Main"], time_multiplier: 1 },
];

vi.mock("@/lib/hooks/use-judge", () => ({
  useJudgeSettings: () => ({ data: settings, isLoading: false }),
  useJudgeLanguages: () => ({ data: languages, isLoading: false }),
  useJudgeLanguagePresets: () => ({ data: presets, isLoading: false }),
  useUpdateJudgeSettings: () => ({ mutate: mockUpdateSettings, isPending: false }),
  useCheckJudgeConnection: () => ({
    mutate: (_: unknown, opts?: MutateOpts) => {
      mockCheck();
      opts?.onSuccess?.(checkResult);
    },
    isPending: false,
  }),
  useApplyJudgeSetup: () => ({ mutate: mockApply, isPending: false }),
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
    endpoint_managed: false,
    ...over,
  };
}

const passing: JudgeCheckResult = {
  ok: true,
  legs: [
    { name: "endpoint_reachable", ok: true, detail: "reachable, Docker API 1.47" },
    { name: "proxy_restricted", ok: true, detail: "exec: blocked; volumes: blocked; build: blocked" },
    { name: "harness_available", ok: true, detail: "judge harness for linux/amd64 is installed" },
    { name: "test_judging", ok: true, detail: "ran a test judging in 0.8s" },
  ],
};
const unrestricted: JudgeCheckResult = {
  ok: false,
  legs: [
    { name: "endpoint_reachable", ok: true, detail: "reachable" },
    { name: "proxy_restricted", ok: false, detail: "exec: NOT blocked" },
  ],
};

const python: JudgeLanguage = {
  id: "lang-1",
  key: "python3",
  name: "Python 3",
  image_ref: "python:3.13-slim",
  source_filename: "solution.py",
  compile_command: null,
  run_command: ["python3", "{source}"],
  time_multiplier: 1,
  enabled: true,
};

beforeEach(() => {
  for (const m of [mockUpdateSettings, mockCheck, mockApply, mockCreate, mockUpdateLanguage, mockToast]) {
    m.mockClear();
  }
  checkResult = passing;
});

describe("JudgeSettingsPanel — setup wizard (judge off)", () => {
  it("shows the overlay command and a prefilled address when nothing is detected", () => {
    settings = baseSettings();
    languages = [];
    renderWithIntl(<JudgeSettingsPanel />);
    expect(screen.getByText("Connect the judge")).toBeInTheDocument();
    expect(
      screen.getByText("docker compose -f docker-compose.yml -f docker-compose.judge.yml up -d"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Proxy address")).toHaveValue("http://socket-proxy:2375");
  });

  it("shows a deployment-managed endpoint as detected, with nothing to type", () => {
    settings = baseSettings({ endpoint_url: "http://judge-proxy:2375", endpoint_managed: true });
    languages = [];
    renderWithIntl(<JudgeSettingsPanel />);
    expect(screen.getByText("Detected from your deployment")).toBeInTheDocument();
    expect(screen.queryByLabelText("Proxy address")).not.toBeInTheDocument();
  });

  it("saves a typed address before checking it — the check only probes the saved one", () => {
    settings = baseSettings();
    languages = [];
    renderWithIntl(<JudgeSettingsPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Check connection" }));

    expect(mockUpdateSettings).toHaveBeenCalledWith(
      { endpoint_url: "http://socket-proxy:2375" },
      expect.anything(),
    );
    expect(mockCheck).toHaveBeenCalledTimes(1);
    expect(mockUpdateSettings.mock.invocationCallOrder[0]).toBeLessThan(
      mockCheck.mock.invocationCallOrder[0],
    );
  });

  it("won't continue past an unrestricted proxy", () => {
    settings = baseSettings({ endpoint_url: "http://socket-proxy:2375" });
    languages = [];
    checkResult = unrestricted;
    renderWithIntl(<JudgeSettingsPanel />);
    const next = screen.getByRole("button", { name: "Next" });
    expect(next).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Check connection" }));
    expect(screen.getByText(/Proxy locked down/)).toBeInTheDocument();
    expect(next).toBeDisabled();
  });

  it("labels every check leg in plain words, including the test judging", () => {
    settings = baseSettings({ endpoint_url: "http://socket-proxy:2375" });
    renderWithIntl(<JudgeSettingsPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Check connection" }));
    for (const label of [
      "Proxy reachable",
      "Proxy locked down",
      "Judge harness installed",
      "Test judging ran",
    ]) {
      expect(screen.getByText(new RegExp(label))).toBeInTheDocument();
    }
    expect(screen.getByText("ran a test judging in 0.8s")).toBeInTheDocument();
  });

  it("pre-ticks Python, C++ and Java, and enables in one atomic call", () => {
    settings = baseSettings({ endpoint_url: "http://socket-proxy:2375" });
    languages = [];
    renderWithIntl(<JudgeSettingsPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Check connection" }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    const box = (name: RegExp) =>
      screen.getAllByRole("checkbox", { name }).find((el) => el.id.startsWith("judge-setup-lang-"))!;
    expect(box(/Python 3/)).toBeChecked();
    expect(box(/C\+\+/)).toBeChecked();
    expect(box(/Java/)).toBeChecked();
    expect(box(/PyPy 3/)).not.toBeChecked();

    // Tick PyPy too; the call keeps catalog order, not click order.
    fireEvent.click(box(/PyPy 3/));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Enable code judge" }));

    expect(mockApply).toHaveBeenCalledWith(["python3", "pypy3", "cpp", "java"], expect.anything());
  });
});

describe("JudgeSettingsPanel — judge on", () => {
  it("summarises the setup, marking a deployment-managed endpoint", () => {
    settings = baseSettings({
      enabled: true,
      endpoint_url: "http://judge-proxy:2375",
      endpoint_managed: true,
    });
    languages = [python];
    renderWithIntl(<JudgeSettingsPanel />);
    expect(screen.getByText("Code judge is on")).toBeInTheDocument();
    // Only the summary carries this badge.
    expect(screen.getByText("From your deployment")).toBeInTheDocument();
    expect(screen.queryByText("Connect the judge")).not.toBeInTheDocument();
  });

  it("re-running setup opens the wizard with a way back", () => {
    settings = baseSettings({ enabled: true, endpoint_url: "http://socket-proxy:2375" });
    languages = [python];
    renderWithIntl(<JudgeSettingsPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Re-run setup" }));
    expect(screen.getByText("Connect the judge")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByText("Code judge is on")).toBeInTheDocument();
  });

  it("a custom language's commands go one argv entry per line; empty compile is null", () => {
    settings = baseSettings({ enabled: true, endpoint_url: "http://socket-proxy:2375" });
    languages = [python];
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

  it("locks a language's key when editing, and never sends it", () => {
    settings = baseSettings({ enabled: true, endpoint_url: "http://socket-proxy:2375" });
    languages = [python];
    renderWithIntl(<JudgeSettingsPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Edit Python 3" }));
    expect(screen.getByLabelText("Key")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Container image"), {
      target: { value: "python:3.14-slim" },
    });
    fireEvent.submit(screen.getByLabelText("Run command").closest("form")!);

    const [{ id, input }] = mockUpdateLanguage.mock.calls[0];
    expect(id).toBe("lang-1");
    expect(input).not.toHaveProperty("key");
  });

  it("shows the command placeholders literally rather than as ICU arguments", () => {
    settings = baseSettings({ enabled: true, endpoint_url: "http://socket-proxy:2375" });
    languages = [python];
    renderWithIntl(<JudgeSettingsPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Add custom language" }));
    expect(screen.getByText("{source}")).toBeInTheDocument();
    expect(screen.getByText("{work}")).toBeInTheDocument();
  });
});
