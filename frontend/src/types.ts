export type DisclosureStatus = "covered" | "partial" | "missing" | "error";
export type RunStatus =
  | "queued"
  | "extracting"
  | "indexing"
  | "judging"
  | "completed"
  | "failed"
  | "cancelled";

export interface ElementJudgment {
  id: string;
  status: "found" | "partial" | "missing";
  page: number | null;
}

export interface FindingView {
  disclosure_id: string;
  standard: string;
  status: DisclosureStatus;
  score: number | null;
  na_reason: string | null;
  note: string;
  evidence_excerpt: string | null;
  evidence_page: number | null;
  elements: ElementJudgment[];
  suggested_fix: string;
  vision_fallback_used: boolean;
}

export interface CorrectionView {
  id: number;
  disclosure_id: string;
  corrected_score: number;
  corrected_elements: ElementJudgment[] | null;
  rationale: string;
  agent_score: number | null;
  reviewer: string;
  created_at: string;
}

export interface RunSummary {
  id: string;
  pdf_filename: string;
  uploaded_at: string;
  completed_at: string | null;
  status: RunStatus;
  error: string | null;
  counts: Partial<Record<DisclosureStatus, number>>;
  // How many disclosures this run judges. null = all.
  selected_total: number | null;
  // Total LLM+embedding spend for this run, including inline retries.
  cost_usd: number;
}

export interface RunDetail {
  summary: RunSummary;
  findings: FindingView[];
  report_id: string;
  version_number: number;
  kind: VersionKind;
  parent_run_id: string | null;
  parent_version_number: number | null;
  corrections: CorrectionView[];
}

export type VersionKind = "initial" | "retry" | "fork" | "update";

export interface VersionSummary {
  run_id: string;
  version_number: number;
  kind: VersionKind;
  parent_run_id: string | null;
  reused_from_run_id: string | null;
  pdf_filename: string;
  pdf_sha256: string;
  status: RunStatus;
  uploaded_at: string;
  completed_at: string | null;
  error: string | null;
  counts: Partial<Record<DisclosureStatus, number>>;
}

export interface ReportSummary {
  id: string;
  name: string;
  created_at: string;
  version_count: number;
  latest: VersionSummary;
}

export interface ReportPage {
  items: ReportSummary[];
  /** Reports matching the current filter — NOT just the ones in `items`. */
  total: number;
  limit: number;
  offset: number;
}

export interface ReportDetail {
  id: string;
  name: string;
  created_at: string;
  runs: VersionSummary[];
}

export interface ReportExportOption {
  report_id: string;
  name: string;
  /** Completed versions only, newest first. */
  versions: { run_id: string; version_number: number }[];
}

export interface KbDisclosure {
  id: string;
  title: string;
  category: "universal" | "topic" | "management" | "sector";
  status: "current" | "superseded" | "upcoming";
  effective_date: string | null;
  effective_until: string | null;
  superseded_by: string | null;
}

export interface KbStandard {
  standard: string;
  disclosures: KbDisclosure[];
}

export interface Preset {
  id: string;
  name: string;
  standard: string;
  disclosure_ids: string[];
}

export type DiffChange =
  | "unchanged"
  | "status_changed"
  | "note_changed"
  | "only_in_a"
  | "only_in_b"
  | "both_missing";

export interface DiffEntry {
  disclosure_id: string;
  standard: string;
  a: FindingView | null;
  b: FindingView | null;
  change: DiffChange;
}

export interface CompareSideSummary {
  run_id: string;
  version_number: number;
  kind: VersionKind;
  pdf_filename: string;
  summary: RunSummary;
}

export interface CompareDelta {
  a: number;
  b: number;
  delta: number;
}

export interface CompareResponse {
  a: CompareSideSummary;
  b: CompareSideSummary;
  diff: DiffEntry[];
  summary_delta: Record<DisclosureStatus, CompareDelta>;
}

export interface MeStats {
  pdf_count: number;
  cost_usd: number;
}

export interface Me {
  username: string;
  is_admin: boolean;
}

export interface AdminUser {
  id: number;
  username: string;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
  pdf_count: number;
  cost_usd: number;
}

export interface CostByKind {
  kind: string;
  call_count: number;
  cost_usd: number;
}

export interface AdminUserRun {
  id: string;
  pdf_filename: string;
  uploaded_at: string;
  completed_at: string | null;
  status: RunStatus;
  run_cost_usd: number;
}

export interface DailyUsage {
  /** Local date (WIB) as YYYY-MM-DD — a day bucket, not an instant. */
  day: string;
  pdf_count: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface AdminUserDetail extends AdminUser {
  last_active: string | null;
  cost_by_kind: CostByKind[];
  recent_runs: AdminUserRun[];
  /** Newest first; only days with activity. Capped at 90 by the API. */
  daily_usage: DailyUsage[];
}

export interface TraceAttempt {
  attempt: number;
  rejudged: boolean;
  parse_path: "structured" | "fallback" | "error" | string;
  error: string | null;
  latency_ms: number | null;
  prompt_hash: string;
  model: string;
  queries: string[];
  chunk_ids: number[];
  distances: number[];
  pages: number[];
  evidence_verified: boolean | null;
  created_at: string;
}

export interface DisclosureTrace {
  disclosure_id: string;
  attempts: TraceAttempt[];
}

export interface TracesResponse {
  run_id: string;
  traces: DisclosureTrace[];
}
