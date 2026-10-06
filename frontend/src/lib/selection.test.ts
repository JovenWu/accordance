import { describe, expect, it } from "vitest";

import {
  categoryOf,
  categoryState,
  compareSelectionChips,
  disclosureVisible,
  groupByCategory,
  isFullyLocked,
  matchesQuery,
  standardState,
  toggleCategory,
  toggleDisclosure,
  toggleStandard,
} from "./selection";
import type { KbDisclosure, KbStandard } from "../types";

const mk = (
  standard: string,
  category: "universal" | "topic" | "sector",
  ids: string[],
): KbStandard => ({
  standard,
  disclosures: ids.map((id) => ({
    id,
    title: id,
    category,
    status: "current",
    effective_date: null,
    effective_until: null,
    superseded_by: null,
  })),
});

const group: KbStandard = {
  standard: "GRI 2",
  disclosures: [
    { id: "2-1", title: "a", category: "universal", status: "current", effective_date: null, effective_until: null, superseded_by: null },
    { id: "2-2", title: "b", category: "universal", status: "current", effective_date: null, effective_until: null, superseded_by: null },
  ],
};

describe("selection helpers", () => {
  it("toggleDisclosure adds then removes an id", () => {
    const once = toggleDisclosure(new Set<string>(), "2-1");
    expect(once.has("2-1")).toBe(true);
    const twice = toggleDisclosure(once, "2-1");
    expect(twice.has("2-1")).toBe(false);
  });

  it("standardState reflects none/some/all", () => {
    expect(standardState(group, new Set())).toBe("unchecked");
    expect(standardState(group, new Set(["2-1"]))).toBe("indeterminate");
    expect(standardState(group, new Set(["2-1", "2-2"]))).toBe("checked");
  });

  it("toggleStandard checks all when not all, clears when all", () => {
    const all = toggleStandard(group, new Set(["2-1"]));
    expect(all.has("2-1") && all.has("2-2")).toBe(true);
    const none = toggleStandard(group, all);
    expect(none.has("2-1") || none.has("2-2")).toBe(false);
  });

  it("counts locked (judged) ids as 'on' for the parent state; toggle still ignores them", () => {
    const locked = new Set(["2-1"]);
    expect(standardState(group, new Set(["2-2"]), locked)).toBe("checked");
    expect(standardState(group, new Set(), locked)).toBe("indeterminate");
    expect(standardState(group, new Set(), new Set(["2-1", "2-2"]))).toBe("checked");
    const toggled = toggleStandard(group, new Set(), locked);
    expect(toggled.has("2-1")).toBe(false);
    expect(toggled.has("2-2")).toBe(true);
  });
});

describe("groupByCategory", () => {
  it("derives a standard's category from its disclosures", () => {
    expect(categoryOf(mk("GRI 305", "topic", ["305-1"]))).toBe("topic");
  });

  it("buckets standards into Universal/Topic/Sector in that order", () => {
    const groups = [
      mk("GRI 305", "topic", ["305-1"]),
      mk("GRI 11", "sector", ["11.1.1"]),
      mk("GRI 2", "universal", ["2-1"]),
    ];
    const result = groupByCategory(groups);
    expect(result.map((c) => c.category)).toEqual([
      "universal",
      "topic",
      "sector",
    ]);
    expect(result.map((c) => c.label)).toEqual(["Universal", "Topic", "Sector"]);
    expect(result[1].standards.map((s) => s.standard)).toEqual(["GRI 305"]);
  });

  it("omits empty categories", () => {
    const result = groupByCategory([mk("GRI 2", "universal", ["2-1"])]);
    expect(result.map((c) => c.category)).toEqual(["universal"]);
  });
});

describe("category select-all helpers", () => {
  const standards = [
    mk("GRI 2", "universal", ["2-1", "2-2"]),
    mk("GRI 3", "universal", ["3-1"]),
  ];

  it("categoryState reflects none/some/all across the category", () => {
    expect(categoryState(standards, new Set())).toBe("unchecked");
    expect(categoryState(standards, new Set(["2-1"]))).toBe("indeterminate");
    expect(categoryState(standards, new Set(["2-1", "2-2", "3-1"]))).toBe(
      "checked",
    );
  });

  it("toggleCategory selects all when not all, clears when all", () => {
    const all = toggleCategory(standards, new Set(["2-1"]));
    expect([...all].sort()).toEqual(["2-1", "2-2", "3-1"]);
    const none = toggleCategory(standards, all);
    expect(none.size).toBe(0);
  });

  it("counts locked ids as 'on' for the category parent; toggle ignores them", () => {
    const locked = new Set(["2-1"]);
    expect(categoryState(standards, new Set(["2-2", "3-1"]), locked)).toBe(
      "checked",
    );
    const toggled = toggleCategory(standards, new Set(), locked);
    expect(toggled.has("2-1")).toBe(false);
    expect([...toggled].sort()).toEqual(["2-2", "3-1"]);
  });

  it("isFullyLocked is true only when every disclosure is locked", () => {
    expect(isFullyLocked(standards, new Set(["2-1", "2-2", "3-1"]))).toBe(true);
    expect(isFullyLocked(standards, new Set(["2-1", "2-2"]))).toBe(false);
    expect(isFullyLocked(standards, new Set())).toBe(false);
  });
});

const disc = (over: Partial<KbDisclosure>): KbDisclosure => ({
  id: "305-1",
  title: "Direct emissions",
  category: "topic",
  status: "current",
  effective_date: null,
  effective_until: null,
  superseded_by: null,
  ...over,
});

describe("matchesQuery", () => {
  it("empty query matches everything", () => {
    expect(matchesQuery(disc({}), "GRI 305: Emissions", "")).toBe(true);
  });
  it("matches on id, title, or standard name (case-insensitive)", () => {
    expect(matchesQuery(disc({}), "GRI 305: Emissions", "305-1")).toBe(true);
    expect(matchesQuery(disc({}), "GRI 305: Emissions", "DIRECT")).toBe(true);
    expect(matchesQuery(disc({}), "GRI 305: Emissions", "emiss")).toBe(true);
    expect(matchesQuery(disc({}), "GRI 305: Emissions", "water")).toBe(false);
  });
});

describe("disclosureVisible", () => {
  const std = "GRI 305: Emissions";
  it("hides non-current under currentOnly unless selected", () => {
    const sup = disc({ id: "x", status: "superseded" });
    expect(
      disclosureVisible(sup, std, {
        query: "",
        currentOnly: true,
        selected: new Set(),
      }),
    ).toBe(false);
    expect(
      disclosureVisible(sup, std, {
        query: "",
        currentOnly: true,
        selected: new Set(["x"]),
      }),
    ).toBe(true);
    expect(
      disclosureVisible(sup, std, {
        query: "",
        currentOnly: false,
        selected: new Set(),
      }),
    ).toBe(true);
  });
  it("combines search AND edition filter", () => {
    const sup = disc({ id: "x", title: "Old metric", status: "superseded" });
    expect(
      disclosureVisible(sup, std, {
        query: "old",
        currentOnly: true,
        selected: new Set(),
      }),
    ).toBe(false);
    expect(
      disclosureVisible(disc({}), std, {
        query: "water",
        currentOnly: true,
        selected: new Set(),
      }),
    ).toBe(false);
  });
});

describe("compareSelectionChips", () => {
  const versions = new Map([
    ["run-a", { version_number: 1 }],
    ["run-b", { version_number: 2 }],
  ]);

  it("maps selected run ids to {runId, versionNumber}", () => {
    expect(compareSelectionChips(["run-a", "run-b"], versions)).toEqual([
      { runId: "run-a", versionNumber: 1 },
      { runId: "run-b", versionNumber: 2 },
    ]);
  });

  it("drops ids whose version was deleted instead of throwing", () => {
    expect(compareSelectionChips(["run-a", "run-gone"], versions)).toEqual([
      { runId: "run-a", versionNumber: 1 },
    ]);
  });
});
