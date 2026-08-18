import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReportsPanel } from "@/components/reports/reports-panel";
import type { CompetitionReport } from "@/lib/types";

const mockCreate = vi.fn();
const mockRemove = vi.fn();
const mockDownload = vi.fn();
let mockReports: CompetitionReport[] = [];

const ALL = ["overview", "participation", "results", "challenges", "support", "feedback"];

vi.mock("@/lib/hooks/use-reports", () => ({
  useReportCatalog: () => ({
    data: {
      sections: ALL.map((id) => ({ id, label: id })),
      presets: {
        executive: ["overview", "participation", "results"],
        technical: ALL,
        full: ALL,
      },
      formats: ["pdf", "html"],
    },
    isLoading: false,
    isError: false,
  }),
  useReports: () => ({ data: mockReports, isLoading: false }),
  useCreateReport: () => ({ mutate: mockCreate, isPending: false }),
  useDeleteReport: () => ({ mutate: mockRemove }),
  useDownloadReport: () => ({ mutate: mockDownload, isPending: false }),
}));

vi.mock("@/components/ui/confirm", () => ({
  useConfirm: () => () => Promise.resolve(true),
}));

vi.mock("@/stores/toast", () => ({ toast: vi.fn() }));

afterEach(() => {
  mockCreate.mockClear();
  mockRemove.mockClear();
  mockDownload.mockClear();
  mockReports = [];
});

describe("ReportsPanel", () => {
  it("blocks generation until the competition has ended", () => {
    render(<ReportsPanel competitionId="c1" status="running" />);
    expect(
      screen.getByText(/generated once the competition has ended/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate report" })).toBeDisabled();
  });

  it("generates with the seeded technical preset + both formats when ended", () => {
    render(<ReportsPanel competitionId="c1" status="ended" />);
    const button = screen.getByRole("button", { name: "Generate report" });
    expect(button).not.toBeDisabled();
    fireEvent.click(button);

    expect(mockCreate).toHaveBeenCalledTimes(1);
    const payload = mockCreate.mock.calls[0][0];
    expect(new Set(payload.sections)).toEqual(new Set(ALL));
    expect(new Set(payload.formats)).toEqual(new Set(["pdf", "html"]));
    expect(payload.preset).toBe("technical");
  });

  it("downloads a ready report through the API hook (not a raw MinIO link)", () => {
    mockReports = [
      {
        id: "r1", version: 2, status: "ready", config: { sections: [], formats: [] },
        error: null, created_at: "2026-10-10T09:00:00Z",
        completed_at: "2026-10-10T09:01:00Z",
        pdf_url: "/api/competitions/c1/reports/r1/download/pdf",
        html_url: "/api/competitions/c1/reports/r1/download/html",
      },
    ];
    render(<ReportsPanel competitionId="c1" status="ended" />);
    expect(screen.getByText("Version 2")).toBeInTheDocument();

    // Buttons, not <a href> — the file is fetched as an auth'd blob so a plain
    // navigation (no bearer token) can't be the download path.
    expect(screen.queryByRole("link", { name: "PDF" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "PDF" }));
    expect(mockDownload).toHaveBeenCalledWith(
      { reportId: "r1", fmt: "pdf", version: 2 },
      expect.anything(),
    );

    fireEvent.click(screen.getByRole("button", { name: "HTML" }));
    expect(mockDownload).toHaveBeenCalledWith(
      { reportId: "r1", fmt: "html", version: 2 },
      expect.anything(),
    );
  });
});
