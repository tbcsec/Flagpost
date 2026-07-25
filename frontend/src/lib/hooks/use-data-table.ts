"use client";

// Headless client-side table state (#16 #17 #20): sort + search + pagination
// over an already-fetched list, derived with useMemo so live-updating data (a
// WS-fed scoreboard, a refetched roster) re-derives automatically. Headless on
// purpose — surfaces keep their bespoke markup (tables *and* card lists) and
// only wire this hook to components/ui/data-table.tsx pieces where they fit.
// No server state here (§8): callers pass rows from their domain hook.

import { useMemo, useState } from "react";

import {
  filterRows,
  paginateRows,
  clampPage,
  pageCount as countPages,
  sortRows,
  type Accessor,
  type SortDir,
} from "@/lib/data-table";

/** A sortable column: a value accessor, optionally with the direction applied
 *  on its *first* click (numeric columns usually want "desc" — points, solves). */
export type ColumnDef<T> = Accessor<T> | { value: Accessor<T>; defaultDir: SortDir };

export interface DataTableOptions<T> {
  /** Sortable columns keyed by a stable id (what toggleSort takes). */
  columns?: Record<string, ColumnDef<T>>;
  /** Fields the search query matches against; omit for no search. */
  searchKeys?: readonly Accessor<T>[];
  /** Starting sort; null (default) keeps the server's order until a header is clicked. */
  initialSort?: { key: string; dir: SortDir } | null;
  initialPageSize?: number;
}

export interface DataTableState<T> {
  /** The rows for the current page, post filter + sort. */
  rows: T[];
  /** Row count after filtering (what pagination is sized against). */
  total: number;
  page: number;
  pageCount: number;
  pageSize: number;
  setPage: (page: number) => void;
  setPageSize: (size: number) => void;
  query: string;
  setQuery: (query: string) => void;
  sort: { key: string; dir: SortDir } | null;
  /** First click applies the column's defaultDir (asc unless declared); a
   *  second click on the same column flips it. Sorting jumps back to page 1. */
  toggleSort: (key: string) => void;
}

export function useDataTable<T>(
  rows: readonly T[],
  options: DataTableOptions<T> = {},
): DataTableState<T> {
  // Options are captured on first render: accessors are declared inline at call
  // sites, so re-reading them every render would bust the memos below for no
  // behavioural gain (column definitions don't change at runtime).
  const [opts] = useState(options);
  const { columns = {}, searchKeys = [] } = opts;

  const [query, setQueryRaw] = useState("");
  const [sort, setSort] = useState(opts.initialSort ?? null);
  const [page, setPageRaw] = useState(0);
  const [pageSize, setPageSizeRaw] = useState(opts.initialPageSize ?? 25);

  const filtered = useMemo(
    () => filterRows(rows, query, searchKeys),
    [rows, query, searchKeys],
  );

  const sorted = useMemo(() => {
    if (!sort) return filtered;
    const column = columns[sort.key];
    if (!column) return filtered;
    const accessor = typeof column === "function" ? column : column.value;
    return sortRows(filtered, accessor, sort.dir);
  }, [filtered, sort, columns]);

  // Clamp instead of resetting state when the dataset shrinks under us (live
  // updates, a narrower search) — the stored page stays put, the view doesn't.
  const clamped = clampPage(page, sorted.length, pageSize);
  const pageRows = useMemo(
    () => paginateRows(sorted, clamped, pageSize),
    [sorted, clamped, pageSize],
  );

  return {
    rows: pageRows,
    total: filtered.length,
    page: clamped,
    pageCount: countPages(filtered.length, pageSize),
    pageSize,
    setPage: (p) => setPageRaw(p),
    setPageSize: (size) => {
      setPageSizeRaw(size);
      setPageRaw(0);
    },
    query,
    setQuery: (q) => {
      setQueryRaw(q);
      setPageRaw(0);
    },
    sort,
    toggleSort: (key) => {
      setSort((current) => {
        if (current?.key === key) {
          return { key, dir: current.dir === "asc" ? "desc" : "asc" };
        }
        const column = columns[key];
        const defaultDir =
          column && typeof column !== "function" ? column.defaultDir : "asc";
        return { key, dir: defaultDir };
      });
      setPageRaw(0);
    },
  };
}
