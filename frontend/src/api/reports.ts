import type {
  CompareResponse,
  ReportDetail,
  ReportPage,
} from "../types";
import { http, request, requestVoid } from "./http";

/** One page of the history list. `q` is matched server-side against the report
 *  name and the latest version's PDF filename. */
export const listReports = (
  opts: { q?: string; limit?: number; offset?: number } = {},
) => {
  const params = new URLSearchParams();
  if (opts.q) params.set("q", opts.q);
  if (opts.limit != null) params.set("limit", String(opts.limit));
  if (opts.offset != null) params.set("offset", String(opts.offset));
  const qs = params.toString();
  return http<ReportPage>(`/reports${qs ? `?${qs}` : ""}`);
};

export const getReport = (id: string) =>
  http<ReportDetail>(`/reports/${id}`);

export const deleteReport = (id: string) =>
  requestVoid(`/reports/${id}`, { method: "DELETE" });

export const renameReport = (id: string, name: string) =>
  request<{ id: string; name: string }>(`/reports/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });

export async function uploadNewVersion(
  reportId: string,
  file: File,
): Promise<{ run_id: string; version_number: number }> {
  const form = new FormData();
  form.append("pdf", file);
  return request(`/reports/${reportId}/versions`, {
    method: "POST",
    body: form,
  });
}

export const compare = (reportId: string, a: string, b: string) =>
  http<CompareResponse>(
    `/reports/${reportId}/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`,
  );

export const exportReportCoverageUrl = (reportId: string) =>
  `/api/reports/${reportId}/export/coverage`;
