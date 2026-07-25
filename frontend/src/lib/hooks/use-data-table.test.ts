import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useDataTable } from "@/lib/hooks/use-data-table";

type Row = { name: string; points: number };

const rows: Row[] = Array.from({ length: 30 }, (_, i) => ({
  name: `player ${i + 1}`,
  points: (i * 7) % 100,
}));

const options = {
  columns: {
    name: (r: Row) => r.name,
    points: { value: (r: Row) => r.points, defaultDir: "desc" as const },
  },
  searchKeys: [(r: Row) => r.name],
  initialPageSize: 10,
};

describe("useDataTable", () => {
  it("keeps server order until a sort is chosen, then pages the sorted set", () => {
    const { result } = renderHook(() => useDataTable(rows, options));
    expect(result.current.sort).toBeNull();
    expect(result.current.rows[0]).toBe(rows[0]);
    expect(result.current.total).toBe(30);
    expect(result.current.pageCount).toBe(3);
  });

  it("toggleSort applies the column defaultDir first, then flips; repeat clicks return to page 1", () => {
    const { result } = renderHook(() => useDataTable(rows, options));

    act(() => result.current.toggleSort("points"));
    expect(result.current.sort).toEqual({ key: "points", dir: "desc" }); // declared defaultDir
    const top = result.current.rows[0].points;
    expect(result.current.rows.every((r) => r.points <= top)).toBe(true);

    act(() => result.current.toggleSort("points"));
    expect(result.current.sort).toEqual({ key: "points", dir: "asc" }); // same column flips

    act(() => result.current.toggleSort("name"));
    expect(result.current.sort).toEqual({ key: "name", dir: "asc" }); // undeclared → asc
  });

  it("search narrows rows and resets to the first page", () => {
    const { result } = renderHook(() => useDataTable(rows, options));
    act(() => result.current.setPage(2));
    expect(result.current.page).toBe(2);

    act(() => result.current.setQuery("player 3"));
    expect(result.current.page).toBe(0);
    // "player 3" and "player 30".
    expect(result.current.total).toBe(2);
  });

  it("clamps the page when the dataset shrinks under it (live updates)", () => {
    const { result, rerender } = renderHook(
      ({ data }: { data: Row[] }) => useDataTable(data, options),
      { initialProps: { data: rows } },
    );
    act(() => result.current.setPage(2));
    expect(result.current.page).toBe(2);

    rerender({ data: rows.slice(0, 5) }); // 30 rows → 5: page 2 no longer exists
    expect(result.current.page).toBe(0);
    expect(result.current.rows).toHaveLength(5);
  });

  it("changing the page size returns to the first page", () => {
    const { result } = renderHook(() => useDataTable(rows, options));
    act(() => result.current.setPage(1));
    act(() => result.current.setPageSize(25));
    expect(result.current.page).toBe(0);
    expect(result.current.pageSize).toBe(25);
    expect(result.current.pageCount).toBe(2);
  });
});
