import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/ui/toast";
import { ReportPage } from "@/pages/ReportPage";

vi.mock("@/api", async () => {
  const actual =
    await vi.importActual<typeof import("@/api")>("@/api");
  return {
    ...actual,
    getReport: vi.fn(),
    deleteReport: vi.fn(),
    deleteRun: vi.fn(),
    forkRun: vi.fn(),
    renameReport: vi.fn(),
    uploadNewVersion: vi.fn(),
    downloadFile: vi.fn(),
    exportReportCoverageUrl: vi.fn(() => ""),
  };
});
import { ApiError, getReport } from "@/api";

function renderAt(reportId = "gone") {
  return render(
    <MemoryRouter initialEntries={[`/reports/${reportId}`]}>
      <ToastProvider>
        <Routes>
          <Route path="/reports/:reportId" element={<ReportPage />} />
        </Routes>
      </ToastProvider>
    </MemoryRouter>,
  );
}

afterEach(() => vi.clearAllMocks());

describe("ReportPage 404 handling", () => {
  it("shows the not-found page instead of loading forever", async () => {
    // Regression: the `!report` guard returned the skeleton before the error
    // was ever rendered, so a deleted report span an idle spinner indefinitely
    // and looked identical to a slow network.
    vi.mocked(getReport).mockRejectedValue(
      new ApiError(404, "404: Report not found"),
    );
    renderAt();

    expect(
      await screen.findByRole("heading", { name: /report not found/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /back to analyses/i }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/loading report/i)).not.toBeInTheDocument();
  });

  it("keeps showing the loading state for a non-404 failure", async () => {
    // A 500 is transient — claiming the report doesn't exist would be a lie.
    vi.mocked(getReport).mockRejectedValue(new ApiError(500, "500: boom"));
    renderAt();

    expect(
      screen.queryByRole("heading", { name: /report not found/i }),
    ).not.toBeInTheDocument();
  });
});
