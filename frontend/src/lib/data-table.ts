// Client-side table transforms — the pure half of the data-table layer
// (#16 pagination / #17 sort / #20 search). React state lives in
// hooks/use-data-table.ts and the UI pieces in components/ui/data-table.tsx;
// these functions stay framework-free so they're unit-testable in isolation.

export type SortDir = "asc" | "desc";

/** What a sortable/searchable column accessor may return for a row. */
export type CellValue = string | number | null | undefined;

export type Accessor<T> = (row: T) => CellValue;

/** The fixed page-size choices (#16: "Display: 10|25|50"). */
export const PAGE_SIZE_OPTIONS = [10, 25, 50] as const;

/** Compare two non-null cell values: numbers numerically, everything else as
 *  case-insensitive strings with natural number handling ("a2" before "a10").
 *  Null handling lives in sortRows, which pins missing values last. */
export function compareValues(a: NonNullable<CellValue>, b: NonNullable<CellValue>): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, {
    sensitivity: "base",
    numeric: true,
  });
}

/** Sort rows by an accessor without mutating the input. Stable (equal keys keep
 *  their incoming order), and null/undefined values sort last in *both*
 *  directions — a missing rating shouldn't float to the top on descending. */
export function sortRows<T>(rows: readonly T[], accessor: Accessor<T>, dir: SortDir): T[] {
  return [...rows].sort((x, y) => {
    const a = accessor(x);
    const b = accessor(y);
    if (a == null && b == null) return 0;
    if (a == null) return 1;
    if (b == null) return -1;
    const cmp = compareValues(a, b);
    return dir === "asc" ? cmp : -cmp;
  });
}

/** Case-insensitive substring filter across the given accessors. An empty (or
 *  whitespace-only) query returns the input array unchanged, same reference. */
export function filterRows<T>(
  rows: readonly T[],
  query: string,
  accessors: readonly Accessor<T>[],
): readonly T[] {
  const q = query.trim().toLowerCase();
  if (!q || accessors.length === 0) return rows;
  return rows.filter((row) =>
    accessors.some((accessor) => {
      const value = accessor(row);
      return value != null && String(value).toLowerCase().includes(q);
    }),
  );
}

/** Total pages for a row count — never less than 1 (an empty table is page 1 of 1). */
export function pageCount(total: number, pageSize: number): number {
  return Math.max(1, Math.ceil(total / pageSize));
}

/** Clamp a 0-based page index into range for the current row count, so a
 *  shrinking dataset (live WS updates, a narrower search) can't strand the
 *  view on a page that no longer exists. */
export function clampPage(page: number, total: number, pageSize: number): number {
  return Math.min(Math.max(0, page), pageCount(total, pageSize) - 1);
}

/** The rows visible on a (clamped) 0-based page. */
export function paginateRows<T>(rows: readonly T[], page: number, pageSize: number): T[] {
  const start = clampPage(page, rows.length, pageSize) * pageSize;
  return rows.slice(start, start + pageSize);
}
