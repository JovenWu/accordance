import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FindingView, RunDetail } from "@/types";
import { FindingsView } from "./FindingsView";

vi.mock("@/lib/useKbTitles", () => ({
  useKbTitles: () => new Map<string, string>(),
}));

const findings: FindingView[] = Array.from({ length: 30 }, (_, i) => ({
  disclosure_id: `2-${i + 1}`,
  standard: "GRI 2",
  status: "partial",
  score: 2,
  na_reason: null,
  note: "Test finding",
  evidence_excerpt: null,
  evidence_page: null,
  elements: [],
  suggested_fix: "",
  vision_fallback_used: false,
}));

const run: RunDetail = {
  summary: {
    id: "run-1",
    pdf_filename: "report.pdf",
    uploaded_at: "2026-10-01T03:11:46.197227Z",
    completed_at: "2026-10-01T03:19:16.875624Z",
    status: "completed",
    error: null,
    counts: { partial: findings.length },
    selected_total: findings.length,
    cost_usd: 0,
  },
  findings,
  report_id: "report-1",
  version_number: 1,
  kind: "initial",
  parent_run_id: null,
  parent_version_number: null,
  corrections: [],
};

describe("FindingsView", () => {
  it("keeps many finding rows in a bounded scroll area", () => {
    const { container } = render(
      <FindingsView
        run={run}
        onChanged={() => {}}
        onCorrect={() => {}}
        onTrace={() => {}}
      />,
    );

    expect(screen.getAllByRole("listitem")).toHaveLength(findings.length);
    // md+: bounded inner scroller; below md the page itself scrolls.
    expect(container.firstElementChild).toHaveClass(
      "md:min-h-0",
      "md:flex-1",
      "md:overflow-hidden",
    );
    expect(
      screen.getByRole("list").closest('[class~="md:overflow-auto"]'),
    ).toHaveClass("md:min-h-0", "md:flex-1");
  });

  it("keeps sr-only row labels inside a positioned ancestor", () => {
    // .sr-only spans are position:absolute. Without a positioned ancestor
    // inside the scroll container, they escape the clip and stretch the
    // document's scrollable height (blank page overflow).
    const { container } = render(
      <FindingsView
        run={run}
        onChanged={() => {}}
        onCorrect={() => {}}
        onTrace={() => {}}
      />,
    );

    const scroller = container.querySelector('[class~="md:overflow-auto"]');
    const positioned = ["relative", "absolute", "fixed", "sticky"];
    for (const sr of container.querySelectorAll(".sr-only")) {
      let el = sr.parentElement;
      let found = false;
      while (el && el !== scroller) {
        if (positioned.some((c) => el!.classList.contains(c))) {
          found = true;
          break;
        }
        el = el.parentElement;
      }
      expect(found, "sr-only label lacks a positioned ancestor").toBe(true);
    }
  });
});
