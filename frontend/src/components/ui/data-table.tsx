"use client";

// UI pieces for the data-table layer (#16 #17 #20), pairing with the headless
// hooks/use-data-table.ts: a sortable column header, a search input, and a
// pagination footer. Each is optional — surfaces adopt only what fits (the
// support card list uses search + pagination with no sortable headers).

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { TableHead } from "@/components/ui/table";
import { PAGE_SIZE_OPTIONS, type SortDir } from "@/lib/data-table";
import { cn } from "@/lib/utils";

// --- Sortable column header (#17) -------------------------------------------

const ARIA_SORT: Record<SortDir, React.AriaAttributes["aria-sort"]> = {
  asc: "ascending",
  desc: "descending",
};

function SortArrow({ dir }: { dir: SortDir | null }) {
  // Inactive columns show a faint two-way glyph so sortability is discoverable;
  // the active column shows a single direction arrow.
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={cn("shrink-0", dir === null && "opacity-40")}
    >
      {dir === "asc" && <path d="m18 15-6-6-6 6" />}
      {dir === "desc" && <path d="m6 9 6 6 6-6" />}
      {dir === null && (
        <>
          <path d="m8 9 4-4 4 4" />
          <path d="m16 15-4 4-4-4" />
        </>
      )}
    </svg>
  );
}

type SortableTableHeadProps = React.ComponentProps<"th"> & {
  /** This column's direction when it is the active sort, else null. */
  active: SortDir | null;
  onSort: () => void;
  /** Match the column's cell alignment (numeric columns are right-aligned). */
  align?: "left" | "right";
};

/** A TableHead whose full area is a sort toggle. Sets aria-sort on the <th>
 *  and keeps the shared header typography; the arrow inherits currentColor. */
const SortableTableHead = React.forwardRef<HTMLTableCellElement, SortableTableHeadProps>(
  ({ active, onSort, align = "left", className, children, ...props }, ref) => (
    <TableHead
      ref={ref}
      aria-sort={active ? ARIA_SORT[active] : "none"}
      className={cn("p-0", className)}
      {...props}
    >
      <button
        type="button"
        onClick={onSort}
        className={cn(
          "flex h-12 w-full items-center gap-1 px-4 font-medium transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset",
          align === "right" && "justify-end",
          active && "text-foreground",
        )}
      >
        {children}
        <SortArrow dir={active} />
      </button>
    </TableHead>
  ),
);
SortableTableHead.displayName = "SortableTableHead";

// --- Search input (#20) ------------------------------------------------------

type TableSearchInputProps = Omit<
  React.ComponentProps<typeof Input>,
  "value" | "onChange"
> & {
  value: string;
  onChange: (value: string) => void;
};

/** A controlled search box sized for table toolbars; the placeholder doubles
 *  as the accessible name. */
const TableSearchInput = React.forwardRef<HTMLInputElement, TableSearchInputProps>(
  ({ value, onChange, placeholder = "Search…", className, ...props }, ref) => (
    <Input
      ref={ref}
      type="search"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      aria-label={props["aria-label"] ?? placeholder}
      className={cn("h-9 max-w-xs", className)}
      {...props}
    />
  ),
);
TableSearchInput.displayName = "TableSearchInput";

// --- Pagination footer (#16) -------------------------------------------------

function Chevron({ direction }: { direction: "left" | "right" }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {direction === "left" ? <path d="m15 18-6-6 6-6" /> : <path d="m9 18 6-6-6-6" />}
    </svg>
  );
}

interface PaginationState {
  total: number;
  page: number;
  pageCount: number;
  pageSize: number;
  setPage: (page: number) => void;
  setPageSize: (size: number) => void;
}

type TablePaginationProps = {
  /** The use-data-table state (structurally — anything with these fields works). */
  table: PaginationState;
  /** What a row is, for the range text — "10 of 43 competitors". */
  noun?: string;
  className?: string;
};

/** "x–y of N" + page-size select + previous/next. Renders nothing when the
 *  whole dataset fits inside the smallest page size — nothing to paginate. */
function TablePagination({ table, noun = "rows", className }: TablePaginationProps) {
  const { total, page, pageCount, pageSize, setPage, setPageSize } = table;
  if (total <= PAGE_SIZE_OPTIONS[0]) return null;

  const from = page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);

  return (
    <div className={cn("flex flex-wrap items-center justify-between gap-3", className)}>
      <p className="text-sm text-muted-foreground">
        {from}–{to} of {total} {noun}
      </p>
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          Display
          <Select
            value={String(pageSize)}
            onChange={(e) => setPageSize(Number(e.target.value))}
            className="h-8 w-auto py-0"
          >
            {PAGE_SIZE_OPTIONS.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </Select>
        </label>
        <Button
          variant="outline"
          size="icon"
          className="h-8 w-8"
          aria-label="Previous page"
          disabled={page === 0}
          onClick={() => setPage(page - 1)}
        >
          <Chevron direction="left" />
        </Button>
        <span className="text-sm text-muted-foreground">
          {page + 1} / {pageCount}
        </span>
        <Button
          variant="outline"
          size="icon"
          className="h-8 w-8"
          aria-label="Next page"
          disabled={page >= pageCount - 1}
          onClick={() => setPage(page + 1)}
        >
          <Chevron direction="right" />
        </Button>
      </div>
    </div>
  );
}

export { SortableTableHead, TableSearchInput, TablePagination };
