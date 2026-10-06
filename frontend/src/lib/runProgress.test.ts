import { describe, expect, it } from "vitest";

import { phaseLabel, progressPct } from "./runProgress";

describe("runProgress", () => {
  it("progressPct computes a clamped percentage", () => {
    expect(progressPct(0, 10)).toBe(0);
    expect(progressPct(5, 10)).toBe(50);
    expect(progressPct(10, 10)).toBe(100);
    expect(progressPct(12, 10)).toBe(100);
    expect(progressPct(3, 0)).toBe(0);
  });

  it("phaseLabel maps non-terminal statuses, empty otherwise", () => {
    expect(phaseLabel("queued")).toMatch(/queued/i);
    expect(phaseLabel("extracting")).toMatch(/extract/i);
    expect(phaseLabel("indexing")).toMatch(/index/i);
    expect(phaseLabel("judging")).toMatch(/judg/i);
    expect(phaseLabel("completed")).toBe("");
  });
});
