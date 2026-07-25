import { describe, expect, it } from "vitest";

import {
  clampPage,
  compareValues,
  filterRows,
  pageCount,
  paginateRows,
  sortRows,
} from "@/lib/data-table";

type Row = { name: string; points: number | null };

const rows: Row[] = [
  { name: "bravo", points: 300 },
  { name: "Alpha", points: 100 },
  { name: "charlie", points: null },
  { name: "delta", points: 200 },
];

describe("compareValues", () => {
  it("compares numbers numerically", () => {
    expect(compareValues(2, 10)).toBeLessThan(0);
  });

  it("compares strings case-insensitively", () => {
    expect(compareValues("Alpha", "bravo")).toBeLessThan(0);
    expect(compareValues("alpha", "ALPHA")).toBe(0);
  });

  it("handles embedded numbers naturally", () => {
    // "challenge 2" should sort before "challenge 10", not after.
    expect(compareValues("challenge 2", "challenge 10")).toBeLessThan(0);
  });
});

describe("sortRows", () => {
  it("sorts ascending and descending without mutating the input", () => {
    const asc = sortRows(rows, (r) => r.name, "asc");
    expect(asc.map((r) => r.name)).toEqual(["Alpha", "bravo", "charlie", "delta"]);
    const desc = sortRows(rows, (r) => r.name, "desc");
    expect(desc.map((r) => r.name)).toEqual(["delta", "charlie", "bravo", "Alpha"]);
    // Input untouched.
    expect(rows[0].name).toBe("bravo");
  });

  it("pins null values last in both directions", () => {
    // A missing value must never float to the top just because the sort flipped.
    const asc = sortRows(rows, (r) => r.points, "asc");
    expect(asc.map((r) => r.points)).toEqual([100, 200, 300, null]);
    const desc = sortRows(rows, (r) => r.points, "desc");
    expect(desc.map((r) => r.points)).toEqual([300, 200, 100, null]);
  });

  it("is stable for equal keys", () => {
    const tied = [
      { name: "first", points: 1 },
      { name: "second", points: 1 },
      { name: "third", points: 1 },
    ];
    const sorted = sortRows(tied, (r) => r.points, "desc");
    expect(sorted.map((r) => r.name)).toEqual(["first", "second", "third"]);
  });
});

describe("filterRows", () => {
  const accessors = [(r: Row) => r.name];

  it("returns the input array unchanged for an empty or whitespace query", () => {
    expect(filterRows(rows, "", accessors)).toBe(rows);
    expect(filterRows(rows, "   ", accessors)).toBe(rows);
  });

  it("matches case-insensitive substrings", () => {
    expect(filterRows(rows, "ALPH", accessors).map((r) => r.name)).toEqual(["Alpha"]);
    expect(filterRows(rows, "a", accessors)).toHaveLength(4); // all contain an "a"
  });

  it("matches across multiple accessors and skips null values", () => {
    const both = [(r: Row) => r.name, (r: Row) => r.points];
    expect(filterRows(rows, "300", both).map((r) => r.name)).toEqual(["bravo"]);
    expect(filterRows(rows, "zzz", both)).toEqual([]);
  });
});

describe("pagination", () => {
  it("pageCount never drops below one page", () => {
    expect(pageCount(0, 10)).toBe(1);
    expect(pageCount(10, 10)).toBe(1);
    expect(pageCount(11, 10)).toBe(2);
  });

  it("clampPage keeps the page in range when the dataset shrinks", () => {
    expect(clampPage(5, 30, 10)).toBe(2); // pages 0..2
    expect(clampPage(-1, 30, 10)).toBe(0);
    expect(clampPage(3, 0, 10)).toBe(0);
  });

  it("paginateRows slices the clamped page", () => {
    const many = Array.from({ length: 25 }, (_, i) => i);
    expect(paginateRows(many, 0, 10)).toEqual(many.slice(0, 10));
    expect(paginateRows(many, 2, 10)).toEqual([20, 21, 22, 23, 24]);
    // An out-of-range page clamps to the last page instead of returning [].
    expect(paginateRows(many, 99, 10)).toEqual([20, 21, 22, 23, 24]);
  });
});
