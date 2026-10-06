import { describe, expect, it } from "vitest";

import { filterUsers, pageCount, sortUsers, summarizeUsers } from "./userTable";
import type { AdminUser } from "@/types";

const u = (over: Partial<AdminUser>): AdminUser => ({
  id: 1, username: "x", is_admin: false, is_active: true,
  created_at: "", pdf_count: 0, cost_usd: 0, ...over,
});

const users: AdminUser[] = [
  u({ id: 1, username: "alice", pdf_count: 12, cost_usd: 4, is_active: true }),
  u({ id: 2, username: "Bob", pdf_count: 3, cost_usd: 1, is_active: false }),
  u({ id: 3, username: "carol", pdf_count: 0, cost_usd: 0, is_active: true }),
];

describe("userTable", () => {
  it("filters by username, case-insensitively", () => {
    expect(filterUsers(users, "bo").map((x) => x.username)).toEqual(["Bob"]);
    expect(filterUsers(users, "").length).toBe(3);
  });

  it("sorts by username asc/desc (case-insensitive)", () => {
    expect(sortUsers(users, "username", "asc").map((x) => x.username)).toEqual(["alice", "Bob", "carol"]);
    expect(sortUsers(users, "username", "desc").map((x) => x.username)).toEqual(["carol", "Bob", "alice"]);
  });

  it("sorts by numeric columns", () => {
    expect(sortUsers(users, "pdf_count", "desc").map((x) => x.pdf_count)).toEqual([12, 3, 0]);
    expect(sortUsers(users, "cost_usd", "asc").map((x) => x.cost_usd)).toEqual([0, 1, 4]);
  });

  it("sorts by status (active first when desc)", () => {
    expect(sortUsers(users, "is_active", "desc").map((x) => x.is_active)).toEqual([true, true, false]);
  });

  it("does not mutate its input", () => {
    const copy = [...users];
    sortUsers(users, "pdf_count", "asc");
    expect(users).toEqual(copy);
  });

  it("computes page count (10 per page)", () => {
    expect(pageCount(0)).toBe(1);
    expect(pageCount(10)).toBe(1);
    expect(pageCount(11)).toBe(2);
  });

  it("summarizes totals", () => {
    expect(summarizeUsers(users)).toEqual({ total: 3, active: 2, pdfs: 15, spend: 5 });
  });
});
