from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from accordance.judge.output_schema import DisclosureStatus, ElementJudgment

RunStatus = Literal[
    "queued",
    "extracting",
    "indexing",
    "judging",
    "completed",
    "failed",
    "cancelled",
]


class RunSummary(BaseModel):
    id: str
    pdf_filename: str
    uploaded_at: datetime
    completed_at: datetime | None
    status: RunStatus
    error: str | None = None
    counts: dict[str, int] = {}
    selected_total: int | None = None
    cost_usd: float = 0.0


class FindingView(BaseModel):
    disclosure_id: str
    standard: str
    status: DisclosureStatus
    score: int | None = None
    na_reason: str | None = None
    note: str
    evidence_excerpt: str | None
    evidence_page: int | None
    elements: list[ElementJudgment]
    suggested_fix: str
    vision_fallback_used: bool


class CorrectionView(BaseModel):
    id: int
    disclosure_id: str
    corrected_score: int
    corrected_elements: list[ElementJudgment] | None = None
    rationale: str
    agent_score: int | None = None
    reviewer: str
    created_at: datetime


VersionKind = Literal["initial", "retry", "fork", "update"]


class RunDetail(BaseModel):
    summary: RunSummary
    findings: list[FindingView]
    corrections: list[CorrectionView] = []
    report_id: str
    version_number: int
    kind: VersionKind
    parent_run_id: str | None
    parent_version_number: int | None


class VersionSummary(BaseModel):
    run_id: str
    version_number: int
    kind: VersionKind
    parent_run_id: str | None
    reused_from_run_id: str | None
    pdf_filename: str
    pdf_sha256: str
    status: RunStatus
    uploaded_at: datetime
    completed_at: datetime | None
    error: str | None = None
    counts: dict[str, int] = {}


class ReportSummary(BaseModel):
    id: str
    name: str
    created_at: datetime
    version_count: int
    latest: VersionSummary


class ReportPage(BaseModel):
    """One page of the history list.

    ``total`` counts every report matching the filter, not just the ones in
    ``items`` — the client needs it to render "Page 2 of 7" without fetching
    everything, which is the whole point of paginating.
    """

    items: list[ReportSummary] = []
    total: int = 0
    limit: int = 0
    offset: int = 0


class ReportDetail(BaseModel):
    id: str
    name: str
    created_at: datetime
    runs: list[VersionSummary]


class ExportVersionOption(BaseModel):
    run_id: str
    version_number: int


class ReportExportOption(BaseModel):
    report_id: str
    name: str
    versions: list[ExportVersionOption]


class MeStats(BaseModel):
    pdf_count: int
    cost_usd: float


class AdminUserView(BaseModel):
    id: int
    username: str
    is_admin: bool
    is_active: bool
    created_at: datetime
    pdf_count: int
    cost_usd: float


class CostByKind(BaseModel):
    kind: str
    call_count: int
    cost_usd: float


class AdminUserRun(BaseModel):
    id: str
    pdf_filename: str
    uploaded_at: datetime
    completed_at: datetime | None
    status: RunStatus
    run_cost_usd: float


class DailyUsage(BaseModel):
    """One calendar day of a user's activity, in the app's display timezone.

    ``day`` is a local date, not an instant — grouping in UTC would file an
    evening run under the previous day for a UTC+7 viewer.
    """

    day: date
    pdf_count: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class AdminUserDetail(AdminUserView):
    last_active: datetime | None = None
    cost_by_kind: list[CostByKind] = []
    recent_runs: list[AdminUserRun] = []
    daily_usage: list[DailyUsage] = []


class DiffEntry(BaseModel):
    disclosure_id: str
    standard: str
    a: FindingView | None
    b: FindingView | None
    change: Literal[
        "unchanged",
        "status_changed",
        "note_changed",
        "only_in_a",
        "only_in_b",
        "both_missing",
    ]


class CompareSideSummary(BaseModel):
    run_id: str
    version_number: int
    kind: VersionKind
    pdf_filename: str
    summary: RunSummary


class CompareDelta(BaseModel):
    a: int
    b: int
    delta: int


class CompareResponse(BaseModel):
    a: CompareSideSummary
    b: CompareSideSummary
    diff: list[DiffEntry]
    summary_delta: dict[str, CompareDelta]
