import type {
  CorrectionView,
  ElementJudgment,
  RunDetail,
  TracesResponse,
} from "../types";
import { http, postJson, request, requestVoid } from "./http";

export interface UploadResult {
  run_id: string;
  report_id: string;
  version_number: number;
  deduplicated?: boolean;
}

export async function uploadPdf(
  file: File,
  disclosureIds?: string[],
): Promise<UploadResult> {
  const form = new FormData();
  form.append("pdf", file);
  if (disclosureIds && disclosureIds.length > 0) {
    form.append("disclosure_ids", JSON.stringify(disclosureIds));
  }
  return request<UploadResult>("/runs", { method: "POST", body: form });
}

export const getRun = (id: string) => http<RunDetail>(`/runs/${id}`);

export const deleteRun = (id: string) =>
  requestVoid(`/runs/${id}`, { method: "DELETE" });

export const judgeMore = (runId: string, disclosureIds: string[]) =>
  postJson<{ run_id: string; judged: string[] }>(`/runs/${runId}/judge-more`, {
    disclosure_ids: disclosureIds,
  });

export const retryRun = (id: string, disclosureIds?: string[]) =>
  disclosureIds === undefined
    ? request<{ run_id: string; version_number: number }>(
        `/runs/${id}/retry`,
        { method: "POST" },
      )
    : postJson<{ run_id: string; version_number: number }>(
        `/runs/${id}/retry`,
        { disclosure_ids: disclosureIds },
      );

export const stopRun = (id: string) =>
  requestVoid(`/runs/${id}/stop`, { method: "POST" });

export const forkRun = (id: string) =>
  request<{ run_id: string; version_number: number }>(`/runs/${id}/fork`, {
    method: "POST",
  });

export const pdfUrl = (id: string) => `/api/runs/${id}/pdf`;

export const getTraces = (runId: string) =>
  http<TracesResponse>(`/runs/${runId}/traces`);

export interface CorrectionCreate {
  disclosure_id: string;
  corrected_score: number;
  corrected_elements?: ElementJudgment[];
  rationale: string;
}

export const saveCorrection = (runId: string, body: CorrectionCreate) =>
  postJson<CorrectionView>(`/runs/${runId}/corrections`, body);

/** Live (non-superseded) corrections only — the drawer shows this list. */
export const listCorrections = (runId: string) =>
  http<CorrectionView[]>(`/runs/${runId}/corrections`);

export const deleteCorrection = (runId: string, cid: number) =>
  requestVoid(`/runs/${runId}/corrections/${cid}`, { method: "DELETE" });
