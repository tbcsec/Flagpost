import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { ThemeManager } from "@/components/admin/theme-manager";
import { THEME_TOKENS } from "@/lib/theme";
import type { ThemePreset } from "@/lib/types";

// Custom brand theme library manager (#323): list, create/validate, delete.

const mockCreate = vi.fn();
const mockUpdate = vi.fn();
const mockDelete = vi.fn();
let mockThemes: ThemePreset[] = [];

vi.mock("@/lib/hooks/use-themes", () => ({
  useThemes: () => ({ data: mockThemes, isLoading: false }),
  useCreateTheme: () => ({ mutate: mockCreate, isPending: false }),
  useUpdateTheme: () => ({ mutate: mockUpdate, isPending: false }),
  useDeleteTheme: () => ({ mutate: mockDelete, isPending: false }),
}));
vi.mock("@/components/ui/confirm", () => ({
  useConfirm: () => () => Promise.resolve(true),
}));
vi.mock("@/stores/toast", () => ({ toast: vi.fn() }));

const TOKENS = Object.fromEntries(THEME_TOKENS.map((t) => [t, "#101010"]));

afterEach(() => {
  mockCreate.mockClear();
  mockUpdate.mockClear();
  mockDelete.mockClear();
  mockThemes = [];
});

describe("ThemeManager", () => {
  it("shows an empty state and opens the editor on New theme", () => {
    renderWithIntl(<ThemeManager />);
    expect(screen.getByText(/no custom themes yet/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /new theme/i }));
    expect(screen.getByLabelText("Id")).toBeInTheDocument();
  });

  it("blocks save until id + name are valid, then creates with a full token pack", () => {
    renderWithIntl(<ThemeManager />);
    fireEvent.click(screen.getByRole("button", { name: /new theme/i }));

    // No id yet → save is refused.
    fireEvent.click(screen.getByRole("button", { name: /save theme/i }));
    expect(mockCreate).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Id"), { target: { value: "acme" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Acme" } });
    fireEvent.click(screen.getByRole("button", { name: /save theme/i }));

    expect(mockCreate).toHaveBeenCalledTimes(1);
    const payload = mockCreate.mock.calls[0][0];
    expect(payload.id).toBe("acme");
    expect(payload.name).toBe("Acme");
    expect(Object.keys(payload.tokens)).toHaveLength(THEME_TOKENS.length);
  });

  it("lists existing themes and deletes on confirm", async () => {
    mockThemes = [
      { id: "brandx", name: "Brand X", mode: "dark", tokens: TOKENS, source: "custom", created_at: "2026-01-01T00:00:00Z" },
    ];
    renderWithIntl(<ThemeManager />);
    expect(screen.getByText("Brand X")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(mockDelete).toHaveBeenCalled());
    expect(mockDelete.mock.calls[0][0]).toBe("brandx");
  });
});
