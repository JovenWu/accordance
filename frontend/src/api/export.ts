import type { ReportExportOption } from "../types";
import { http } from "./http";

export const exportRunCoverageUrl = (runId: string) =>
  `/api/runs/${runId}/export/coverage`;

export const exportRunAnalysisUrl = (runId: string) =>
  `/api/runs/${runId}/export/analysis`;

export const getExportOptions = () =>
  http<ReportExportOption[]>("/reports/export/options");

export const exportSelectedCoverageUrl = (runIds: string[]) =>
  `/api/reports/export/coverage?runs=${runIds.map(encodeURIComponent).join(",")}`;
