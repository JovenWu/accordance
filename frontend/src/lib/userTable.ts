// frontend/src/lib/userTable.ts
import type { AdminUser } from "@/types";

export type SortKey = "username" | "pdf_count" | "cost_usd" | "is_active";
export type SortDir = "asc" | "desc";
export const PAGE_SIZE = 10;

export function filterUsers(users: AdminUser[], query: string): AdminUser[] {
  const q = query.trim().toLowerCase();
  if (!q) return users;
  return users.filter((u) => u.username.toLowerCase().includes(q));
}

export function sortUsers(users: AdminUser[], key: SortKey, dir: SortDir): AdminUser[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...users].sort((a, b) => {
    let cmp: number;
    if (key === "username") {
      cmp = a.username.toLowerCase().localeCompare(b.username.toLowerCase());
    } else if (key === "is_active") {
      cmp = Number(a.is_active) - Number(b.is_active);
    } else {
      cmp = a[key] - b[key];
    }
    return cmp * sign;
  });
}

export function pageCount(total: number, size: number = PAGE_SIZE): number {
  return Math.max(1, Math.ceil(total / size));
}

export function summarizeUsers(users: AdminUser[]): {
  total: number; active: number; pdfs: number; spend: number;
} {
  return users.reduce(
    (acc, u) => ({
      total: acc.total + 1,
      active: acc.active + (u.is_active ? 1 : 0),
      pdfs: acc.pdfs + u.pdf_count,
      spend: acc.spend + u.cost_usd,
    }),
    { total: 0, active: 0, pdfs: 0, spend: 0 },
  );
}
