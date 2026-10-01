import { describe, expect, it } from "vitest";

import { exportReportCoverageUrl } from "./reports";
import { exportRunCoverageUrl, exportSelectedCoverageUrl } from "./export";

describe("coverage export URLs", () => {
  it("builds the single-run url", () => {
    expect(exportRunCoverageUrl("run1")).toBe("/api/runs/run1/export/coverage");
  });
  it("builds the per-report url", () => {
    expect(exportReportCoverageUrl("abc")).toBe(
      "/api/reports/abc/export/coverage",
    );
  });
  it("builds the selected-runs url with comma-separated run ids", () => {
    expect(exportSelectedCoverageUrl(["r1", "r2"])).toBe(
      "/api/reports/export/coverage?runs=r1,r2",
    );
  });
});
