import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import {
  SortableTableHead,
  TablePagination,
} from "@/components/ui/data-table";

function renderHead(active: "asc" | "desc" | null, onSort = vi.fn()) {
  renderWithIntl(
    <table>
      <thead>
        <tr>
          <SortableTableHead active={active} onSort={onSort}>
            Points
          </SortableTableHead>
        </tr>
      </thead>
    </table>,
  );
  return onSort;
}

describe("SortableTableHead", () => {
  it("exposes the sort state via aria-sort on the header cell", () => {
    renderHead(null);
    expect(screen.getByRole("columnheader")).toHaveAttribute("aria-sort", "none");
  });

  it("maps active directions to ascending/descending", () => {
    renderHead("desc");
    expect(screen.getByRole("columnheader")).toHaveAttribute("aria-sort", "descending");
  });

  it("fires onSort when the header button is clicked", () => {
    const onSort = renderHead(null);
    fireEvent.click(screen.getByRole("button", { name: "Points" }));
    expect(onSort).toHaveBeenCalledOnce();
  });
});

function paginationState(overrides: Partial<Parameters<typeof TablePagination>[0]["table"]> = {}) {
  return {
    total: 60,
    page: 0,
    pageCount: 3,
    pageSize: 25,
    setPage: vi.fn(),
    setPageSize: vi.fn(),
    ...overrides,
  };
}

describe("TablePagination", () => {
  it("renders nothing when the dataset fits in the smallest page size", () => {
    const { container } = renderWithIntl(<TablePagination table={paginationState({ total: 10 })} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the visible range and disables Previous on the first page", () => {
    renderWithIntl(<TablePagination table={paginationState()} noun="competitors" />);
    expect(screen.getByText("1–25 of 60 competitors")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next page" })).toBeEnabled();
  });

  it("disables Next on the last page", () => {
    renderWithIntl(<TablePagination table={paginationState({ page: 2 })} />);
    expect(screen.getByText("51–60 of 60 rows")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });

  it("steps pages and changes the page size through the state callbacks", () => {
    const state = paginationState();
    renderWithIntl(<TablePagination table={state} />);
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(state.setPage).toHaveBeenCalledWith(1);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "50" } });
    expect(state.setPageSize).toHaveBeenCalledWith(50);
  });
});
