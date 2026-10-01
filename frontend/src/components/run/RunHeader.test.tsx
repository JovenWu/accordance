import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/ui/toast";
import type { FindingView, KbStandard, RunDetail } from "@/types";
import { RunHeader } from "./RunHeader";

vi.mock("@/api", async () => {
  const actual =
    await vi.importActual<typeof import("@/api")>("@/api");
  return {
    ...actual,
    getKb: vi.fn(),
    getPresets: vi.fn(async () => []),
    judgeMore: vi.fn(),
    exportRunCoverageUrl: vi.fn(() => "/api/runs/run-1/export/coverage"),
    exportRunAnalysisUrl: vi.fn(() => "/api/runs/run-1/export/analysis"),
  };
});
import { getKb, judgeMore } from "@/api";

const finding = (id: string, status: FindingView["status"]): FindingView => ({
  disclosure_id: id,
  standard: "GRI 2",
  status,
  score: 3,
  na_reason: null,
  note: "",
  evidence_excerpt: null,
  evidence_page: null,
  elements: [],
  suggested_fix: "",
  vision_fallback_used: false,
});

const disclosure = (id: string) => ({
  id,
  title: `${id} title`,
  category: "universal" as const,
  status: "current" as const,
  effective_date: null,
  effective_until: null,
  superseded_by: null,
});

const kb: KbStandard[] = [
  {
    standard: "GRI 2: General Disclosures 2021",
    disclosures: [disclosure("2-1"), disclosure("2-2")],
  },
];

const run: RunDetail = {
  summary: {
    id: "run-1",
    pdf_filename: "report.pdf",
    uploaded_at: "2026-10-01T03:11:46.197227Z",
    completed_at: "2026-10-01T03:19:16.875624Z",
    status: "completed",
    error: null,
    counts: {},
    selected_total: 30,
    cost_usd: 0,
  },
  findings: [],
  report_id: "report-1",
  version_number: 1,
  kind: "initial",
  parent_run_id: null,
  parent_version_number: null,
  corrections: [],
};

afterEach(() => vi.clearAllMocks());

describe("RunHeader", () => {
  it("opens an export menu offering Excel and PDF formats", async () => {
    const open = vi
      .spyOn(window, "open")
      .mockImplementation(() => null);
    render(
      <ToastProvider>
        <RunHeader run={run} onChanged={() => {}} />
      </ToastProvider>,
    );

    await userEvent.click(screen.getByRole("button", { name: /^export$/i }));
    const menu = await screen.findByRole("menu");

    await userEvent.click(
      within(menu).getByRole("menuitem", { name: /excel/i }),
    );
    expect(open).toHaveBeenCalledWith(
      "/api/runs/run-1/export/coverage",
      "_self",
    );

    await userEvent.click(screen.getByRole("button", { name: /^export$/i }));
    const pdfItem = await screen.findByRole("menuitem", { name: /pdf/i });
    expect(pdfItem).not.toHaveAttribute("aria-disabled", "true");
    await userEvent.click(pdfItem);
    expect(open).toHaveBeenCalledWith(
      "/api/runs/run-1/export/analysis",
      "_self",
    );
  });

  it("judges only newly selected disclosures via judge-more", async () => {
    vi.mocked(getKb).mockResolvedValue(kb);
    vi.mocked(judgeMore).mockResolvedValue({
      run_id: "run-1",
      judged: ["2-2"],
    });
    const onChanged = vi.fn();
    const withFinding: RunDetail = {
      ...run,
      findings: [finding("2-1", "covered")],
    };

    render(
      <ToastProvider>
        <RunHeader run={withFinding} onChanged={onChanged} />
      </ToastProvider>,
    );

    await userEvent.click(
      screen.getByRole("button", { name: /add disclosures/i }),
    );
    const dialog = await screen.findByRole("dialog");

    // Already-judged disclosures are locked — they can't be re-requested.
    const judged = within(dialog).getByRole("checkbox", { name: "2-1" });
    expect(judged).toBeDisabled();
    expect(judged).toBeChecked();

    await userEvent.click(
      within(dialog).getByRole("checkbox", { name: "2-2" }),
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: /use scope/i }),
    );

    expect(judgeMore).toHaveBeenCalledWith("run-1", ["2-2"]);
    expect(onChanged).toHaveBeenCalled();
  });
});
