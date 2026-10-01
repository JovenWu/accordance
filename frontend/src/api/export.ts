import type { ReportExportOption } from "../types";
import { http } from "./http";

export const exportRunCoverageUrl = (runId: string) =>
  `/api/runs/${runId}/export/coverage`;

/** One-page PDF analysis report — completed runs only. */
export const exportRunAnalysisUrl = (runId: string) =>
  `/api/runs/${runId}/export/analysis`;

/** Reports that can be exported, each with their completed versions (for the
 * export dialog). */
export const getExportOptions = () =>
  http<ReportExportOption[]>("/reports/export/options");

/** Combined coverage export for an explicit selection of runs (one column each). */
export const exportSelectedCoverageUrl = (runIds: string[]) =>
  `/api/reports/export/coverage?runs=${runIds.map(encodeURIComponent).join(",")}`;
