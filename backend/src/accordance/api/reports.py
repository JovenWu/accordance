"""Reports CRUD + summary endpoints.

Reports group multiple Versions (runs) of the same PDF analysis. List
view shows one row per Report with the latest Version's counts; detail
view shows all Versions DESC by version_number.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from accordance.api.ownership import assert_report_access, visible_reports_clause
from accordance.api.runs import _open_conn
from accordance.auth.deps import require_user
from accordance.config import Settings, get_settings
from accordance.judge.rollup import effective_score
from accordance.models import (
    CompareDelta,
    CompareResponse,
    CompareSideSummary,
    DiffEntry,
    FindingView,
    ReportDetail,
    ReportPage,
    ReportSummary,
    RunSummary,
    VersionSummary,
)

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _row_to_version_summary(conn, row, counts: dict[str, int] | None = None) -> VersionSummary:
    """Build a VersionSummary for one run row.

    ``counts`` lets a caller that already batched the finding counts for a whole
    page pass them in; leaving it None keeps the original per-row query for the
    single-run callers.
    """
    if counts is None:
        counts_rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM findings WHERE run_id=%s GROUP BY status",
            (row["id"],),
        ).fetchall()
        counts = {r["status"]: r["n"] for r in counts_rows}
    return VersionSummary(
        run_id=row["id"],
        version_number=row["version_number"],
        kind=row["kind"],
        parent_run_id=row["parent_run_id"],
        reused_from_run_id=row["reused_from_run_id"],
        pdf_filename=row["pdf_filename"],
        pdf_sha256=row["pdf_sha256"],
        status=row["status"],
        uploaded_at=row["uploaded_at"],
        completed_at=row["completed_at"],
        error=row["error"],
        counts=counts,
    )


MAX_PAGE_SIZE = 100

# Latest run per report + that report's run count, resolved in SQL rather than
# with a query per report. The old loop was N+1 AND sorted in Python after
# fetching everything, which is exactly what makes pagination impossible: you
# cannot LIMIT before you have ordered, and you cannot order by the latest
# run's uploaded_at while that value is only known row-by-row in Python.
#
# The JOIN to `latest` also drops reports with no runs at all (empty shells),
# preserving the old loop's `if latest_row is None: continue`.
_LIST_FROM = """
FROM reports
JOIN LATERAL (
    SELECT * FROM runs
    WHERE runs.report_id = reports.id
    ORDER BY runs.version_number DESC
    LIMIT 1
) latest ON TRUE
WHERE reports.deleted_at IS NULL
"""


def _search_clause(q: str) -> tuple[str, list]:
    """ILIKE filter over the report name and the latest version's filename.

    Both columns, mirroring the client: a report can be renamed after upload,
    so the label on screen and the PDF the user remembers can differ.

    The wildcards in the user's own text are escaped — otherwise typing '%'
    silently matches every report, and '_' matches any character, which reads
    as the search being broken rather than as pattern syntax.
    """
    if not q:
        return "", []
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    return (
        " AND (reports.name ILIKE %s ESCAPE '\\' "
        "OR latest.pdf_filename ILIKE %s ESCAPE '\\')",
        [pattern, pattern],
    )


def _counts_by_run(conn, run_ids: list[str]) -> dict[str, dict[str, int]]:
    """Finding counts for a whole page in ONE query.

    Called per row this was the second half of the N+1; batched it is a single
    round trip whatever the page size.
    """
    if not run_ids:
        return {}
    rows = conn.execute(
        "SELECT run_id, status, COUNT(*) AS n FROM findings "
        "WHERE run_id = ANY(%s) GROUP BY run_id, status",
        (run_ids,),
    ).fetchall()
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        out.setdefault(r["run_id"], {})[r["status"]] = r["n"]
    return out


@router.get("", response_model=ReportPage)
def list_reports(
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """One page of the caller's reports, newest activity first.

    ``q`` matches the report name or the latest version's PDF filename.
    """
    q = q.strip()
    with _open_conn(settings) as conn:
        own_clause, own_params = visible_reports_clause(user)
        search_sql, search_params = _search_clause(q)
        where = _LIST_FROM + " " + own_clause + search_sql
        where_params = own_params + search_params

        total = conn.execute("SELECT COUNT(*) AS n " + where, where_params).fetchone()["n"]

        rows = conn.execute(
            # NOT reports.id — latest.* carries its own `id` (the run id) and
            # would shadow it in the row dict. latest.report_id is the same
            # value by the join condition, so take the report id from there.
            "SELECT reports.name, reports.created_at, latest.* "
            + where
            # reports.id breaks ties. Without a unique tiebreaker, two reports
            # sharing an uploaded_at order nondeterministically between the
            # page-1 and page-2 queries — the classic way a row appears twice,
            # or never, while paging.
            + " ORDER BY latest.uploaded_at DESC, reports.id DESC"
            " LIMIT %s OFFSET %s",
            [*where_params, limit, offset],
        ).fetchall()

        counts = _counts_by_run(conn, [r["id"] for r in rows])
        version_counts = _version_counts(conn, [r["report_id"] for r in rows])

        items = [
            ReportSummary(
                id=r["report_id"],
                name=r["name"],
                created_at=r["created_at"],
                version_count=version_counts.get(r["report_id"], 1),
                latest=_row_to_version_summary(conn, r, counts.get(r["id"], {})),
            )
            for r in rows
        ]
        return ReportPage(items=items, total=total, limit=limit, offset=offset)


def _version_counts(conn, report_ids: list[str]) -> dict[str, int]:
    """Run count per report for a whole page, in one query."""
    if not report_ids:
        return {}
    rows = conn.execute(
        "SELECT report_id, COUNT(*) AS n FROM runs WHERE report_id = ANY(%s) GROUP BY report_id",
        (report_ids,),
    ).fetchall()
    return {r["report_id"]: r["n"] for r in rows}


@router.get("/{report_id}", response_model=ReportDetail)
def get_report(
    report_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    with _open_conn(settings) as conn:
        assert_report_access(conn, report_id, user)
        rep = conn.execute(
            "SELECT * FROM reports WHERE id=%s AND deleted_at IS NULL",
            (report_id,),
        ).fetchone()
        if not rep:
            raise HTTPException(404, "Report not found")
        rows = conn.execute(
            "SELECT * FROM runs WHERE report_id=%s ORDER BY version_number DESC",
            (report_id,),
        ).fetchall()
        return ReportDetail(
            id=rep["id"],
            name=rep["name"],
            created_at=rep["created_at"],
            runs=[_row_to_version_summary(conn, r) for r in rows],
        )


@router.delete("/{report_id}", status_code=204)
def delete_report(
    report_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    with _open_conn(settings) as conn:
        assert_report_access(conn, report_id, user)
        rep = conn.execute("SELECT id FROM reports WHERE id=%s", (report_id,)).fetchone()
        if not rep:
            raise HTTPException(404, "Report not found")

        rows = conn.execute(
            "SELECT id, pdf_path FROM runs WHERE report_id=%s", (report_id,)
        ).fetchall()
        pdf_paths: set[str] = {r["pdf_path"] for r in rows}

        # One DELETE cascades to runs → chunks/findings/judge_traces/assessor_corrections
        # via ON DELETE CASCADE defined in the Postgres schema. No need to manually
        # delete child tables or manage explicit FTS/vector rows (those don't exist
        # in Postgres — FTS is a generated tsvector column, embedding is on chunks).
        with conn.transaction():
            conn.execute("DELETE FROM reports WHERE id=%s", (report_id,))

        for p in pdf_paths:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass
    return Response(status_code=204)


class ReportRename(BaseModel):
    name: str = Field(min_length=1)


@router.patch("/{report_id}")
def rename_report(
    report_id: str,
    payload: ReportRename,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    """Rename a report (the analysis).

    Trims surrounding whitespace; an empty / whitespace-only name is rejected
    (422). Returns the report id + the saved name.
    """
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "Name must not be empty")
    with _open_conn(settings) as conn:
        assert_report_access(conn, report_id, user)
        rep = conn.execute(
            "SELECT id FROM reports WHERE id=%s AND deleted_at IS NULL", (report_id,)
        ).fetchone()
        if not rep:
            raise HTTPException(404, "Report not found")
        # Pooled connections run in autocommit mode, so this UPDATE is durable
        # immediately — no explicit commit needed. The rename test confirms
        # persistence via a fresh-connection GET.
        conn.execute("UPDATE reports SET name=%s WHERE id=%s", (name, report_id))
        return {"id": report_id, "name": name}


# ---------------------------------------------------------------------------
# Compare helpers
# ---------------------------------------------------------------------------


def _row_to_finding_view(row) -> FindingView:
    score = effective_score(row)
    return FindingView(
        disclosure_id=row["disclosure_id"],
        standard=row["standard"],
        status=row["status"],
        score=score,
        na_reason=row["na_reason"],
        note=row["note"],
        evidence_excerpt=row["evidence_excerpt"],
        evidence_page=row["evidence_page"],
        elements=json.loads(row["elements_json"]),
        suggested_fix=row["suggested_fix"],
        vision_fallback_used=bool(row["vision_fallback_used"]),
    )


def _findings_by_disclosure(conn, run_id: str) -> dict[str, Any]:
    return {
        r["disclosure_id"]: r
        for r in conn.execute("SELECT * FROM findings WHERE run_id=%s", (run_id,)).fetchall()
    }


def _classify(a_row, b_row) -> str:
    if a_row is None and b_row is None:
        return "both_missing"
    if a_row is None:
        return "only_in_b"
    if b_row is None:
        return "only_in_a"
    if effective_score(a_row) != effective_score(b_row):
        return "status_changed"
    same_note = (
        a_row["note"] == b_row["note"]
        and a_row["evidence_excerpt"] == b_row["evidence_excerpt"]
        and a_row["evidence_page"] == b_row["evidence_page"]
        and a_row["elements_json"] == b_row["elements_json"]
        and a_row["suggested_fix"] == b_row["suggested_fix"]
    )
    return "unchanged" if same_note else "note_changed"


@router.get("/{report_id}/compare", response_model=CompareResponse)
def compare(
    report_id: str,
    a: str,
    b: str,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    with _open_conn(settings) as conn:
        assert_report_access(conn, report_id, user)
        rep = conn.execute(
            "SELECT id, name FROM reports WHERE id=%s AND deleted_at IS NULL",
            (report_id,),
        ).fetchone()
        if not rep:
            raise HTTPException(404, "Report not found")

        rows = conn.execute("SELECT * FROM runs WHERE id IN (%s, %s)", (a, b)).fetchall()
        by_id = {r["id"]: r for r in rows}
        if a not in by_id or b not in by_id:
            raise HTTPException(404, "Run not found")
        if by_id[a]["report_id"] != report_id or by_id[b]["report_id"] != report_id:
            raise HTTPException(400, "Both runs must belong to this report.")

        a_findings = _findings_by_disclosure(conn, a)
        b_findings = _findings_by_disclosure(conn, b)
        all_ids = sorted(set(a_findings) | set(b_findings))

        diff: list[DiffEntry] = []
        for did in all_ids:
            ar = a_findings.get(did)
            br = b_findings.get(did)
            standard = (ar or br)["standard"]
            diff.append(
                DiffEntry(
                    disclosure_id=did,
                    standard=standard,
                    a=_row_to_finding_view(ar) if ar else None,
                    b=_row_to_finding_view(br) if br else None,
                    change=_classify(ar, br),
                )
            )

        def counts(run_id: str) -> dict[str, int]:
            d: dict[str, int] = {"covered": 0, "partial": 0, "missing": 0, "error": 0}
            for r in conn.execute(
                "SELECT status, COUNT(*) AS n FROM findings WHERE run_id=%s GROUP BY status",
                (run_id,),
            ):
                d[r["status"]] = r["n"]
            return d

        ac = counts(a)
        bc = counts(b)
        delta = {
            k: CompareDelta(a=ac[k], b=bc[k], delta=bc[k] - ac[k])
            for k in ("covered", "partial", "missing", "error")
        }

        def side(run_row) -> CompareSideSummary:
            return CompareSideSummary(
                run_id=run_row["id"],
                version_number=run_row["version_number"],
                kind=run_row["kind"],
                pdf_filename=run_row["pdf_filename"],
                summary=RunSummary(
                    id=run_row["id"],
                    pdf_filename=run_row["pdf_filename"],
                    uploaded_at=run_row["uploaded_at"],
                    completed_at=run_row["completed_at"],
                    status=run_row["status"],
                    error=run_row["error"],
                    counts={k: v for k, v in counts(run_row["id"]).items() if v},
                ),
            )

        return CompareResponse(a=side(by_id[a]), b=side(by_id[b]), diff=diff, summary_delta=delta)
