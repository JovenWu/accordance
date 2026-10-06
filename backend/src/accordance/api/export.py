from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from accordance.api.kb import KB_DIR
from accordance.api.ownership import assert_report_access, assert_run_access, visible_reports_clause
from accordance.api.runs import _open_conn
from accordance.auth.deps import require_user
from accordance.config import Settings, get_settings
from accordance.exporters.analysis_report import (
    AnalysisReport,
    StandardSummary,
    analysis_report_bytes,
)
from accordance.exporters.coverage_matrix import MatrixColumn, build_coverage_matrix
from accordance.exporters.xlsx_exporter import to_xlsx_bytes
from accordance.judge.rollup import effective_score
from accordance.kb.loader import load_kb
from accordance.models import ExportVersionOption, ReportExportOption

router = APIRouter(prefix="/api/runs", tags=["export"])
reports_router = APIRouter(prefix="/api/reports", tags=["export"])

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MEDIA = "application/pdf"


def _score_by_id(conn, run_id: str) -> dict[str, int | None]:
    """Map each judged disclosure to its 0-5 grade (0 = N/A) for this run.

    Uses ``effective_score`` so legacy findings (status only, no score column)
    are back-mapped consistently with the rest of the app. None = judge error.

    Live assessor corrections are then overlaid as authoritative, exactly as the
    UI's ``effectiveGrade`` does — otherwise saved feedback never reached the
    Excel export. A correction can exist without a finding (the assessor graded a
    disclosure the agent didn't), so it can also add a disclosure to the map.
    """
    rows = conn.execute(
        "SELECT disclosure_id, score, status FROM findings WHERE run_id=%s", (run_id,)
    ).fetchall()
    scores: dict[str, int | None] = {r["disclosure_id"]: effective_score(r) for r in rows}

    corrections = conn.execute(
        "SELECT disclosure_id, corrected_score FROM assessor_corrections "
        "WHERE run_id=%s AND superseded=FALSE",
        (run_id,),
    ).fetchall()
    for c in corrections:
        scores[c["disclosure_id"]] = c["corrected_score"]
    return scores


def _safe_filename(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)
    return cleaned.strip("-") or "report"


def _xlsx_response(columns: list[MatrixColumn], filename: str) -> Response:
    matrix = build_coverage_matrix(load_kb(KB_DIR), columns)
    return Response(
        content=to_xlsx_bytes(matrix),
        media_type=XLSX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{run_id}/export/coverage")
def export_run_coverage(
    run_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    """Single-run coverage matrix: one column for this run (header = report vN)."""
    with _open_conn(settings) as conn:
        assert_run_access(conn, run_id, user)
        run = conn.execute(
            "SELECT r.version_number, rep.name AS report_name "
            "FROM runs r JOIN reports rep ON rep.id = r.report_id "
            "WHERE r.id = %s",
            (run_id,),
        ).fetchone()
        if run is None:
            raise HTTPException(404, "Run not found")
        version = run["version_number"]
        column = MatrixColumn(
            label=f"{run['report_name']} v{version}",
            score_by_id=_score_by_id(conn, run_id),
        )
        filename = f"coverage-{_safe_filename(run['report_name'])}-v{version}.xlsx"
        return _xlsx_response([column], filename)


@router.get("/{run_id}/export/analysis")
def export_run_analysis(
    run_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    """One-page PDF analysis summary for a completed run: headline metrics,
    grade distribution, per-standard rollups and a verification block (run id
    + document SHA-256) — so the PDF is traceable back to the source."""
    with _open_conn(settings) as conn:
        assert_run_access(conn, run_id, user)
        run = conn.execute(
            "SELECT r.version_number, r.status, r.pdf_filename, r.pdf_sha256, "
            "r.completed_at, rep.name AS report_name "
            "FROM runs r JOIN reports rep ON rep.id = r.report_id "
            "WHERE r.id = %s",
            (run_id,),
        ).fetchone()
        if run is None:
            raise HTTPException(404, "Run not found")
        if run["status"] != "completed":
            raise HTTPException(
                400, "Analysis report is only available for completed runs."
            )
        page_count = conn.execute(
            "SELECT MAX(page) AS p FROM chunks WHERE run_id=%s", (run_id,)
        ).fetchone()["p"] or 0
        scores = _score_by_id(conn, run_id)

    kb = load_kb(KB_DIR)
    dist: dict[int, int] = {s: 0 for s in range(6)}
    errors = 0
    scored_sum = scored_n = 0
    rollups: dict[str, dict] = {}
    for did, v in scores.items():
        disc = kb.get(did)
        st = rollups.setdefault(
            disc.standard if disc else "Other",
            {"assessed": 0, "scored": 0, "sum": 0},
        )
        if v is None:
            errors += 1
            continue
        dist[v] += 1
        st["assessed"] += 1
        if v > 0:
            st["scored"] += 1
            st["sum"] += v
            scored_sum += v
            scored_n += 1

    def _cov(s: int, n: int) -> float | None:
        return s / (n * 5) if n else None

    standards = [
        StandardSummary(
            name=name,
            assessed=r["assessed"],
            scored=r["scored"],
            avg=(r["sum"] / r["scored"]) if r["scored"] else None,
            coverage=_cov(r["sum"], r["scored"]),
        )
        for name, r in sorted(rollups.items())
    ]
    data = AnalysisReport(
        report_name=run["report_name"],
        version=run["version_number"],
        pdf_filename=run["pdf_filename"],
        run_id=run_id,
        pdf_sha256=run["pdf_sha256"],
        completed_at=run["completed_at"],
        page_count=page_count,
        dist=dist,
        errors=errors,
        coverage=_cov(scored_sum, scored_n),
        avg=(scored_sum / scored_n) if scored_n else None,
        standards=standards,
    )
    filename = (
        f"analysis-{_safe_filename(run['report_name'])}-v{run['version_number']}.pdf"
    )
    return Response(
        content=analysis_report_bytes(data),
        media_type=PDF_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@reports_router.get("/export/options", response_model=list[ReportExportOption])
def export_options(
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    """Reports that can be exported (>= 1 completed run), each with their
    completed versions newest-first — populates the export dialog."""
    with _open_conn(settings) as conn:
        clause, params = visible_reports_clause(user)
        reports = conn.execute(
            "SELECT id, name FROM reports WHERE deleted_at IS NULL "
            f"{clause} ORDER BY created_at ASC",
            params,
        ).fetchall()
        out: list[ReportExportOption] = []
        for rep in reports:
            versions = conn.execute(
                "SELECT id AS run_id, version_number FROM runs "
                "WHERE report_id=%s AND status='completed' ORDER BY version_number DESC",
                (rep["id"],),
            ).fetchall()
            if not versions:
                continue
            out.append(
                ReportExportOption(
                    report_id=rep["id"],
                    name=rep["name"],
                    versions=[
                        ExportVersionOption(run_id=v["run_id"], version_number=v["version_number"])
                        for v in versions
                    ],
                )
            )
        return out


@reports_router.get("/export/coverage")
def export_selected_coverage(
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
    runs: str = Query("", description="Comma-separated run ids — one column per run"),
):
    """Combined coverage matrix for an explicit selection of runs: one column per
    run (in the given order), each at the chosen version. Each run must be a
    completed run. Replaces the old "export every report's latest" behavior."""
    run_ids = [r.strip() for r in runs.split(",") if r.strip()]
    if not run_ids:
        raise HTTPException(400, "Select at least one report to export.")
    with _open_conn(settings) as conn:
        columns: list[MatrixColumn] = []
        first_name: str | None = None
        first_version: int | None = None
        for run_id in run_ids:
            assert_run_access(conn, run_id, user)
            row = conn.execute(
                "SELECT r.version_number, r.status, rep.name AS report_name "
                "FROM runs r JOIN reports rep ON rep.id = r.report_id "
                "WHERE r.id = %s",
                (run_id,),
            ).fetchone()
            if row is None or row["status"] != "completed":
                raise HTTPException(400, f"Run {run_id!r} is not available for export.")
            columns.append(
                MatrixColumn(
                    label=f"{row['report_name']} v{row['version_number']}",
                    score_by_id=_score_by_id(conn, run_id),
                )
            )
            if first_name is None:
                first_name = row["report_name"]
                first_version = row["version_number"]
        filename = (
            f"coverage-{_safe_filename(first_name)}-v{first_version}.xlsx"
            if len(columns) == 1
            else "gri-coverage-matrix.xlsx"
        )
        return _xlsx_response(columns, filename)


@reports_router.get("/{report_id}/export/coverage")
def export_report_coverage(
    report_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    with _open_conn(settings) as conn:
        assert_report_access(conn, report_id, user)
        report = conn.execute(
            "SELECT name FROM reports WHERE id=%s AND deleted_at IS NULL", (report_id,)
        ).fetchone()
        if report is None:
            raise HTTPException(404, "Report not found")
        runs = conn.execute(
            "SELECT id, version_number FROM runs WHERE report_id=%s AND status='completed' "
            "ORDER BY version_number ASC",
            (report_id,),
        ).fetchall()
        if not runs:
            raise HTTPException(404, "No completed runs to export")
        columns = [
            MatrixColumn(label=f"v{r['version_number']}", score_by_id=_score_by_id(conn, r["id"]))
            for r in runs
        ]
        return _xlsx_response(columns, f"coverage-{_safe_filename(report['name'])}.xlsx")
