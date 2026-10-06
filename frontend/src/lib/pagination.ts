export type PageItem = number | "ellipsis";

export function paginationItems(
  current: number,
  totalPages: number,
  siblings = 1,
): PageItem[] {
  if (totalPages <= 0) return [];
  const clamped = Math.min(Math.max(current, 1), totalPages);

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
      if (p - prev === 2) out.push(prev + 1);
      else if (p - prev > 2) out.push("ellipsis");
    }
    out.push(p);
    prev = p;
  }
  return out;
}

export function itemRange(
  offset: number,
  pageItemCount: number,
  total: number,
): { from: number; to: number } {
  if (total === 0 || pageItemCount === 0) return { from: 0, to: 0 };
  const from = offset + 1;
  return { from, to: Math.min(offset + pageItemCount, total) };
}
