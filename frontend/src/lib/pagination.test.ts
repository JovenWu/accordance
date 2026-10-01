import { describe, expect, it } from "vitest";

import { itemRange, paginationItems } from "./pagination";

describe("paginationItems", () => {
  it("lists every page when they all fit", () => {
    expect(paginationItems(1, 5)).toEqual([1, 2, 3, 4, 5]);
  });

  it("returns nothing when there are no pages", () => {
    expect(paginationItems(1, 0)).toEqual([]);
  });

  it("keeps first and last reachable from the middle of a long run", () => {
    // 100 pages — the case Prev/Next alone can't serve.
    expect(paginationItems(50, 100)).toEqual([1, "ellipsis", 49, 50, 51, "ellipsis", 100]);
  });

  it("drops the leading ellipsis near the start", () => {
    expect(paginationItems(2, 100)).toEqual([1, 2, 3, "ellipsis", 100]);
  });

  it("drops the trailing ellipsis near the end", () => {
    expect(paginationItems(99, 100)).toEqual([1, "ellipsis", 98, 99, 100]);
  });

  it("shows a single skipped page instead of an ellipsis", () => {
    // 8 pages, window on 4 → keeps {1,3,4,5,8}. The 1→3 gap is one page, so it
    // renders as "2"; the 5→8 gap is two, so it collapses. An "…" hiding a
    // single number is wider than the number it hides.
    expect(paginationItems(4, 8)).toEqual([1, 2, 3, 4, 5, "ellipsis", 8]);
  });

  it("lists everything at the windowing threshold rather than eliding one page", () => {
    // siblings=1 → widest windowed form is 7 slots, so 7 pages list in full.
    expect(paginationItems(4, 7)).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });

  it("never emits a duplicate or out-of-range page", () => {
    for (let total = 1; total <= 40; total++) {
      for (let cur = 1; cur <= total; cur++) {
        const items = paginationItems(cur, total);
        const nums = items.filter((i): i is number => typeof i === "number");
        expect(new Set(nums).size).toBe(nums.length);
        expect(Math.min(...nums)).toBeGreaterThanOrEqual(1);
        expect(Math.max(...nums)).toBeLessThanOrEqual(total);
        // Always ascending, so the rendered row reads left to right.
        expect([...nums].sort((a, b) => a - b)).toEqual(nums);
        // The current page is always rendered — otherwise nothing is highlighted.
        expect(nums).toContain(cur);
      }
    }
  });

  it("clamps a current page outside the range", () => {
    expect(paginationItems(0, 5)).toEqual([1, 2, 3, 4, 5]);
    expect(paginationItems(99, 5)).toEqual([1, 2, 3, 4, 5]);
  });

  it("widens the window with more siblings", () => {
    expect(paginationItems(50, 100, 2)).toEqual([
      1,
      "ellipsis",
      48,
      49,
      50,
      51,
      52,
      "ellipsis",
      100,
    ]);
  });
});

describe("itemRange", () => {
  it("describes a full page", () => {
    expect(itemRange(10, 10, 234)).toEqual({ from: 11, to: 20 });
  });

  it("stops at the total on a partial last page", () => {
    expect(itemRange(230, 4, 234)).toEqual({ from: 231, to: 234 });
  });

  it("is empty when there is nothing to show", () => {
    expect(itemRange(0, 0, 0)).toEqual({ from: 0, to: 0 });
  });
});
