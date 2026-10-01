// frontend/src/lib/pagination.ts

/** A rendered slot in the pager: a 1-indexed page number, or a gap marker. */
export type PageItem = number | "ellipsis";

/**
 * Which page numbers to render, with gaps collapsed to an ellipsis.
 *
 * Always keeps the first and last page reachable in one click, plus a window of
 * `siblings` either side of the current page, so the control stays a fixed
 * width whether there are 3 pages or 300. A thousand reports at 10/page is 100
 * pages — listing them all is unusable, and Prev/Next alone means 50 clicks to
 * reach the middle.
 */
export function paginationItems(
  current: number,
  totalPages: number,
  siblings = 1,
): PageItem[] {
  if (totalPages <= 0) return [];
  const clamped = Math.min(Math.max(current, 1), totalPages);

  // Widest the windowed form can get: first + … + (siblings·2+1) + … + last.
  // At or below that, windowing would render an ellipsis standing in for
  // fewer pages than it costs in width, so just list them all.
  const widest = siblings * 2 + 5;
  if (totalPages <= widest) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }

  const keep = new Set<number>([1, totalPages]);
  for (
    let p = Math.max(1, clamped - siblings);
    p <= Math.min(totalPages, clamped + siblings);
    p++
  ) {
    keep.add(p);
  }

  const sorted = [...keep].sort((a, b) => a - b);
  const out: PageItem[] = [];
  let prev: number | null = null;
  for (const p of sorted) {
    if (prev !== null) {
      // A gap of exactly one page renders as that page, not as "…". Hiding a
      // single number behind an ellipsis is both wider and less useful than
      // just showing it.
      if (p - prev === 2) out.push(prev + 1);
      else if (p - prev > 2) out.push("ellipsis");
    }
    out.push(p);
    prev = p;
  }
  return out;
}

/** Inclusive 1-indexed range of items shown, for "Showing 11–20 of 234". */
export function itemRange(
  offset: number,
  pageItemCount: number,
  total: number,
): { from: number; to: number } {
  if (total === 0 || pageItemCount === 0) return { from: 0, to: 0 };
  const from = offset + 1;
  return { from, to: Math.min(offset + pageItemCount, total) };
}
