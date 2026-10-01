import hashlib
import json
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from accordance.api.cancellation import registry as cancel_registry
from accordance.api.ownership import assert_run_access
from accordance.auth.deps import require_user
from accordance.config import Settings, embedding_credentials, get_settings, resolve_pdf_path
from accordance.db import connection as _db_connection
from accordance.indexer.embedder import build_embedder
from accordance.judge.output_schema import ElementJudgment
from accordance.judge.rollup import effective_score
from accordance.kb.loader import load_kb
from accordance.llm.adapter import build_llm
from accordance.models import CorrectionView, FindingView, RunDetail, RunSummary

router = APIRouter(prefix="/api/runs", tags=["runs"])


KB_DIR = Path(__file__).resolve().parents[4] / "kb" / "gri"


class JudgeMoreRequest(BaseModel):
    disclosure_ids: list[str]


class RetryRequest(BaseModel):
    disclosure_ids: list[str] | None = None


class CorrectionCreate(BaseModel):
    disclosure_id: str
    corrected_score: int = Field(ge=0, le=5)
    corrected_elements: list[ElementJudgment] | None = None
    rationale: str = Field(min_length=1)


def _row_to_correction(row) -> CorrectionView:
    raw = row["corrected_elements_json"]
    elements = [ElementJudgment.model_validate(e) for e in json.loads(raw)] if raw else None
    return CorrectionView(
        id=row["id"],
        disclosure_id=row["disclosure_id"],
        corrected_score=row["corrected_score"],
        corrected_elements=elements,
        rationale=row["rationale"],
        agent_score=row["agent_score"],
        reviewer=row["reviewer"],
        created_at=row["created_at"],
    )


def _parse_disclosure_ids(raw: str | None) -> list[str] | None:
    """Parse + validate the optional disclosure_ids form field.

    None / absent  → None (judge all). Present → must be a non-empty list of
    ids that all exist in the KB; raises HTTPException(400) otherwise.
    """
    if raw is None or raw.strip() == "":
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "disclosure_ids must be a JSON array") from None
    if parsed is None:
        return None
    if not isinstance(parsed, list) or not all(isinstance(x, str) for x in parsed):
        raise HTTPException(400, "disclosure_ids must be an array of strings")
    if len(parsed) == 0:
        raise HTTPException(400, "Select at least one disclosure")
    valid = set(load_kb(KB_DIR).keys())
    unknown = [i for i in parsed if i not in valid]
    if unknown:
        raise HTTPException(400, f"Unknown disclosure ids: {unknown}")
    return sorted(set(parsed))


def _require_pdf_magic(body: bytes) -> None:
    """Reject a body that isn't actually a PDF (must start with the %PDF- header).

    The content-type gate accepts application/octet-stream (the default the
    browser sends for many uploads), so without this a renamed .png/.zip/etc.
    would be persisted, a run row created, and the failure deferred to a raw
    parser error deep in the worker. Fail fast at the door with a clean 400.
    """
    if not body.startswith(b"%PDF-"):
        raise HTTPException(400, "Uploaded file is not a valid PDF (missing %PDF- header).")


async def _read_upload_capped(pdf: UploadFile, max_bytes: int) -> bytes:
    """Read the whole UploadFile, aborting with 413 once it exceeds max_bytes.

    Reading in chunks bounds peak memory: we stop as soon as the limit is
    crossed instead of materializing an arbitrarily large body first (an
    unbounded ``await pdf.read()`` is a memory-exhaustion DoS).
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await pdf.read(1024 * 1024)  # 1 MiB
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                413, f"Uploaded file exceeds the {max_bytes // (1024 * 1024)} MB limit."
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _open_conn(settings: Settings):
    # Borrow a pooled connection. Schema is ensured once at startup (lifespan),
    # not per request. Returns a context manager: `with _open_conn(s) as conn:`.
    return _db_connection()


_INFLIGHT_STATUSES = ("queued", "extracting", "indexing", "judging")


def _enforce_run_quota(conn, user_id, settings: Settings) -> None:
    """Reject a new run when the acting user already has too many in-flight runs.

    Bounds unbounded worker-thread spawn and runaway paid-LLM spend from a
    looping or compromised account (a run-creating endpoint otherwise spawns a
    thread per request with no per-user cap). Raises HTTPException(429) over the
    limit. No-op when the limit is 0/disabled or the user is unknown.
    """
    limit = int(getattr(settings, "max_inflight_runs_per_user", 0) or 0)
    if limit <= 0 or user_id is None:
        return
    placeholders = ",".join(["%s"] * len(_INFLIGHT_STATUSES))
    n = conn.execute(
        f"SELECT COUNT(*) AS n FROM runs WHERE created_by=%s AND status IN ({placeholders})",
        (user_id, *_INFLIGHT_STATUSES),
    ).fetchone()["n"]
    if n >= limit:
        raise HTTPException(
            429,
            f"You already have {n} run(s) in progress (limit {limit}); "
            "wait for one to finish before starting another.",
        )


# --- Run admission + graceful drain -----------------------------------------
# A bounded semaphore caps how many run workers execute concurrently (each opens
# up to judge_concurrency Postgres connections — unbounded fan-out under a burst
# can exhaust the connection pool). _active_runs lets shutdown cancel + join
# in-progress workers so a SIGTERM/deploy doesn't kill a run mid-write.
_run_admission: threading.BoundedSemaphore | None = None
_admission_lock = threading.Lock()
_active_runs: dict[threading.Thread, str] = {}
_active_runs_lock = threading.Lock()


def _admission_semaphore(settings: Settings) -> threading.BoundedSemaphore:
    global _run_admission
    with _admission_lock:
        if _run_admission is None:
            limit = max(1, int(getattr(settings, "max_concurrent_runs", 4) or 4))
            _run_admission = threading.BoundedSemaphore(limit)
    return _run_admission


def _spawn_admitted(
    settings: Settings, work: Callable[[], None], *, run_id: str
) -> threading.Thread:
    """Run ``work`` on a daemon thread, but only after acquiring an admission
    slot (so concurrent runs are bounded), and tracked so shutdown can drain it.
    """
    sem = _admission_semaphore(settings)

    def runner() -> None:
        sem.acquire()
        try:
            work()
        finally:
            sem.release()
            with _active_runs_lock:
                _active_runs.pop(threading.current_thread(), None)

    t = threading.Thread(target=runner, daemon=True)
    with _active_runs_lock:
        _active_runs[t] = run_id
    t.start()
    return t


def drain_active_runs(timeout: float = 25.0) -> int:
    """Cooperatively cancel in-progress runs and wait (up to ``timeout`` total)
    for their worker threads, so a SIGTERM (docker stop / deploy) doesn't kill a
    run mid-write. Returns how many runs were active when drain began.
    """
    from accordance.api.cancellation import registry as cancel_registry

    with _active_runs_lock:
        items = list(_active_runs.items())
    for _t, rid in items:
        cancel_registry.cancel(rid)
    deadline = time.monotonic() + timeout
    for t, _rid in items:
        remaining = max(0.0, deadline - time.monotonic())
        t.join(timeout=remaining)
    return len(items)


def _kick_off_graph(
    run_id: str,
    pdf_path: Path,
    settings: Settings,
    *,
    reuse_index: bool = False,
    disclosure_ids: list[str] | None = None,
    prepare: Callable[..., None] | None = None,
) -> None:
    """Kick off the LangGraph run in a background thread.

    v1: in-process thread is acceptable for local-first. Promote to a real
    queue (arq, dramatiq) only when needed.

    ``prepare`` runs once inside the worker thread (with the worker's
    connection) before the graph starts — used by retry/fork to copy the
    parent run's chunks off the request path so the HTTP response, and thus
    the client-side reroute to the new run, returns immediately.
    """
    from accordance.graph.build import run_graph

    def worker():
        with _open_conn(settings) as conn:
            try:
                if prepare is not None:
                    prepare(conn)
                kb = load_kb(KB_DIR)
                api_key, emb_base_url = embedding_credentials(settings)
                embedder = build_embedder(
                    settings.embedding_model,
                    api_key=api_key,
                    timeout=settings.embedding_timeout,
                    max_retries=settings.embedding_max_retries,
                    base_url=emb_base_url,
                )
                llm = build_llm(
                    settings.llm_model,
                    base_url=settings.llm_base_url,
                    api_key=settings.llm_api_key,
                    max_retries=settings.llm_max_retries,
                    timeout=settings.llm_timeout,
                    reasoning_effort=settings.llm_reasoning_effort,
                    service_tier=settings.llm_service_tier,
                )
                run_graph(
                    run_id=run_id,
                    pdf_path=pdf_path,
                    kb=kb,
                    conn=conn,
                    embedder=embedder,
                    llm=llm,
                    retrieval_mode=settings.retrieval_mode,
                    reuse_index=reuse_index,
                    disclosure_ids=disclosure_ids,
                )
            except Exception as e:
                # Best-effort: never let the worker thread die before marking the
                # run failed (a raised status-write would leave it stuck 'queued').
                try:
                    conn.execute(
                        "UPDATE runs SET status=%s, error=%s WHERE id=%s",
                        ("failed", str(e), run_id),
                    )
                except Exception:
                    pass
                # Emit a terminal SSE event. Without it the /stream generator only
                # returns on 'completed'/'cancelled', so a watched failed run leaks
                # an open connection + subscriber queue looping on keepalives until
                # the client navigates away. No error text in the payload (the
                # client reads details via GET /runs/{id}); this just signals end.
                try:
                    from accordance.api.events import bus

                    bus.publish(run_id, {"type": "failed"})
                except Exception:
                    pass

    _spawn_admitted(settings, worker, run_id=run_id)


def _persist_new_run(
    body: bytes,
    disclosure_ids_raw: str | None,
    filename: str,
    settings: Settings,
    user_id,
) -> dict:
    """Blocking section of create_run: validate, hash, dedup, write PDF, insert.

    Runs in a threadpool (via ``run_in_threadpool``) so the sha256 over a body up
    to ``max_upload_mb`` (default 100 MB), the on-disk PDF write, and the DB
    insert never execute on the asyncio event loop — blocking it there freezes
    every concurrent SSE progress stream and the /health probe for the duration.
    Returns ``{"dedup": <payload>}`` for a duplicate upload, else
    ``{"created": (run_id, report_id, pdf_path), "selected": <list|None>}``.
    """
    selected = _parse_disclosure_ids(disclosure_ids_raw)
    _require_pdf_magic(body)
    sha = hashlib.sha256(body).hexdigest()

    with _open_conn(settings) as conn:
        existing = conn.execute(
            """
            SELECT r.id AS run_id, r.report_id, r.version_number
            FROM runs r
            JOIN reports rep ON r.report_id = rep.id
            WHERE r.pdf_sha256 = %s
              AND rep.deleted_at IS NULL
            ORDER BY r.uploaded_at DESC
            LIMIT 1
            """,
            (sha,),
        ).fetchone()
        if existing:
            return {
                "dedup": {
                    "run_id": existing["run_id"],
                    "report_id": existing["report_id"],
                    "version_number": existing["version_number"],
                    "deduplicated": True,
                }
            }

        # A genuinely new run will spawn a worker — enforce the per-user quota
        # (a dedup hit above reuses an existing run, so it's exempt).
        _enforce_run_quota(conn, user_id, settings)

        report_id = "rep_" + uuid.uuid4().hex[:24]
        run_id = str(uuid.uuid4())
        settings.pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = settings.pdf_dir / f"{run_id}.pdf"
        pdf_path.write_bytes(body)

        with conn.transaction():
            conn.execute(
                "INSERT INTO reports (id, name, created_by) VALUES (%s, %s, %s)",
                (report_id, filename, user_id),
            )
            conn.execute(
                """
                INSERT INTO runs (
                    id, report_id, parent_run_id, version_number, kind,
                    reused_from_run_id, pdf_filename, pdf_sha256, pdf_path, status,
                    selected_disclosures, created_by
                ) VALUES (%s, %s, NULL, 1, 'initial', NULL, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    report_id,
                    filename,
                    sha,
                    str(pdf_path),
                    "queued",
                    json.dumps(selected) if selected else None,
                    user_id,
                ),
            )

    return {"created": (run_id, report_id, pdf_path), "selected": selected}


@router.post("", status_code=201)
async def create_run(
    pdf: Annotated[UploadFile, File()],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
    disclosure_ids: Annotated[str | None, Form()] = None,
):
    if pdf.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(400, f"Unsupported content type: {pdf.content_type}")
    body = await _read_upload_capped(pdf, settings.max_upload_mb * 1024 * 1024)
    filename = pdf.filename or "upload.pdf"
    # Offload the CPU/disk-bound section so the event loop stays free.
    result = await run_in_threadpool(
        _persist_new_run, body, disclosure_ids, filename, settings, user["id"]
    )

    dedup = result.get("dedup")
    if dedup is not None:
        return JSONResponse(dedup, status_code=200)

    run_id, report_id, pdf_path = result["created"]
    _kick_off_graph(run_id, pdf_path, settings, disclosure_ids=result["selected"])
    return {"run_id": run_id, "report_id": report_id, "version_number": 1}


@router.post("/{run_id}/judge-more", status_code=200)
def judge_more(
    run_id: str,
    payload: JudgeMoreRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    """Judge additional disclosures on an existing run, reusing its index.

    Additive: only disclosures without an existing finding are judged; results
    are upserted into the same run. The selection on the run is expanded to the
    union. The run must be in a terminal state.
    """
    requested = _parse_disclosure_ids(json.dumps(payload.disclosure_ids))
    if requested is None:
        raise HTTPException(400, "Select at least one disclosure")

    with _open_conn(settings) as conn:
        assert_run_access(conn, run_id, user)
        run = conn.execute(
            "SELECT id, status, selected_disclosures, pdf_path FROM runs WHERE id=%s",
            (run_id,),
        ).fetchone()
        if not run:
            raise HTTPException(404, "Run not found")
        if run["status"] not in {"completed", "failed", "cancelled"}:
            raise HTTPException(
                409,
                f"Cannot judge more on a run in status '{run['status']}'; wait for it to finish.",
            )
        _enforce_run_quota(conn, user["id"], settings)

        # Errored findings stay eligible: a disclosure that failed (bad JSON
        # from the model, a dead endpoint) HAS a row, so an unconditional skip
        # left no way to repair it except spawning a whole new run version.
        # Re-judging writes through the findings upsert, and the retry's tokens
        # land in llm_usage against this run, so the run's spend stays honest.
        # Successful findings are still skipped — silently re-judging them
        # would cost money and churn verdicts against a 13%/24% run-to-run
        # noise floor.
        already = {
            r["disclosure_id"]
            for r in conn.execute(
                "SELECT disclosure_id FROM findings WHERE run_id=%s AND status <> 'error'",
                (run_id,),
            )
        }
        to_judge = [i for i in requested if i not in already]
        if not to_judge:
            return {"run_id": run_id, "judged": []}

        # CLAIM the run before touching anything else. The status check above is
        # a read, so two requests can both see 'completed' and both kick off a
        # graph on the same run_id — two thread pools writing the same findings.
        # That was a wide race when judge-more was a deliberate multi-select
        # action; the per-row Retry button makes rapid double-fire ordinary.
        # Re-asserting the terminal status inside the UPDATE closes it: under
        # READ COMMITTED the loser blocks on the row lock, then re-evaluates the
        # WHERE against the winner's committed 'judging' and matches nothing.
        claimed = conn.execute(
            "UPDATE runs SET status='judging', completed_at=NULL "
            "WHERE id=%s AND status IN ('completed','failed','cancelled')",
            (run_id,),
        )
        if claimed.rowcount == 0:
            raise HTTPException(
                409,
                "Another judge-more request for this run started first; "
                "wait for it to finish.",
            )

        # Expand stored selection to the union. NULL meant "all" — leave NULL.
        # After the claim, so a request that lost the race leaves no trace.
        if run["selected_disclosures"] is not None:
            prior = set(json.loads(run["selected_disclosures"]))
            new_selection = sorted(prior | set(to_judge))
            conn.execute(
                "UPDATE runs SET selected_disclosures=%s WHERE id=%s",
                (json.dumps(new_selection), run_id),
            )

        pdf_path = run["pdf_path"]

    cancel_registry.clear(run_id)
    _kick_off_graph(
        run_id,
        resolve_pdf_path(pdf_path, settings),
        settings,
        reuse_index=True,
        disclosure_ids=to_judge,
    )
    return {"run_id": run_id, "judged": to_judge}


@router.post("/{run_id}/corrections", status_code=201)
def create_correction(
    run_id: str,
    payload: CorrectionCreate,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    with _open_conn(settings) as conn:
        assert_run_access(conn, run_id, user)
        if not conn.execute("SELECT 1 FROM runs WHERE id=%s", (run_id,)).fetchone():
            raise HTTPException(404, "Run not found")
        kb = load_kb(KB_DIR)
        if payload.disclosure_id not in kb:
            raise HTTPException(400, f"Unknown disclosure id: {payload.disclosure_id}")

        frow = conn.execute(
            "SELECT * FROM findings WHERE run_id=%s AND disclosure_id=%s",
            (run_id, payload.disclosure_id),
        ).fetchone()
        agent_score = effective_score(frow) if frow else None
        agent_status = frow["status"] if frow else None
        standard = frow["standard"] if frow else kb[payload.disclosure_id].standard

        trow = conn.execute(
            "SELECT prompt_hash, model, chunk_ids_json, pages_json FROM judge_traces "
            "WHERE run_id=%s AND disclosure_id=%s ORDER BY id DESC LIMIT 1",
            (run_id, payload.disclosure_id),
        ).fetchone()
        prompt_hash = trow["prompt_hash"] if trow else None
        model = trow["model"] if trow else None
        chunk_ids_json = trow["chunk_ids_json"] if trow else "[]"
        pages_json = trow["pages_json"] if trow else "[]"

        elements_json = (
            json.dumps([e.model_dump(mode="json") for e in payload.corrected_elements])
            if payload.corrected_elements
            else None
        )

        # Wrap the supersede UPDATE and INSERT in a single transaction so the
        # disclosure never has zero live rows if the process dies between them.
        with conn.transaction():
            conn.execute(
                "UPDATE assessor_corrections SET superseded=TRUE "
                "WHERE run_id=%s AND disclosure_id=%s AND superseded=FALSE",
                (run_id, payload.disclosure_id),
            )
            new_id = conn.execute(
                "INSERT INTO assessor_corrections "
                "(run_id, disclosure_id, standard, corrected_score, corrected_elements_json, "
                " rationale, agent_score, agent_status, prompt_hash, model, chunk_ids_json, "
                " pages_json, reviewer) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    run_id,
                    payload.disclosure_id,
                    standard,
                    payload.corrected_score,
                    elements_json,
                    payload.rationale,
                    agent_score,
                    agent_status,
                    prompt_hash,
                    model,
                    chunk_ids_json,
                    pages_json,
                    user["username"],
                ),
            ).fetchone()["id"]

        row = conn.execute("SELECT * FROM assessor_corrections WHERE id=%s", (new_id,)).fetchone()
        return _row_to_correction(row).model_dump(mode="json")


@router.get("/{run_id}/corrections")
def list_corrections(
    run_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    with _open_conn(settings) as conn:
        assert_run_access(conn, run_id, user)
        rows = conn.execute(
            "SELECT * FROM assessor_corrections "
            "WHERE run_id=%s AND superseded=FALSE ORDER BY disclosure_id",
            (run_id,),
        ).fetchall()
        return [_row_to_correction(r).model_dump(mode="json") for r in rows]


@router.delete("/{run_id}/corrections/{cid}", status_code=204)
def delete_correction(
    run_id: str,
    cid: int,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    with _open_conn(settings) as conn:
        assert_run_access(conn, run_id, user)
        row = conn.execute(
            "SELECT id FROM assessor_corrections WHERE id=%s AND run_id=%s",
            (cid, run_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Correction not found")
        conn.execute("UPDATE assessor_corrections SET superseded=TRUE WHERE id=%s", (cid,))
    return Response(status_code=204)


def _row_to_summary(row) -> RunSummary:
    sel = row["selected_disclosures"] if "selected_disclosures" in row.keys() else None
    return RunSummary(
        id=row["id"],
        pdf_filename=row["pdf_filename"],
        uploaded_at=row["uploaded_at"],
        completed_at=row["completed_at"],
        status=row["status"],
        error=row["error"] if "error" in row.keys() else None,
        selected_total=len(json.loads(sel)) if sel else None,
    )


def _attach_counts(conn, summary: RunSummary) -> RunSummary:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM findings WHERE run_id=%s GROUP BY status",
        (summary.id,),
    ).fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    summary.counts = counts
    cost = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) AS c FROM llm_usage WHERE run_id=%s",
        (summary.id,),
    ).fetchone()
    summary.cost_usd = float(cost["c"] if cost else 0.0)
    return summary


@router.get("/{run_id}")
def get_run(
    run_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    with _open_conn(settings) as conn:
        assert_run_access(conn, run_id, user)
        run = conn.execute("SELECT * FROM runs WHERE id=%s", (run_id,)).fetchone()
        if not run:
            raise HTTPException(404, "Run not found")
        summary = _attach_counts(conn, _row_to_summary(run))
        finding_rows = conn.execute(
            "SELECT * FROM findings WHERE run_id=%s ORDER BY disclosure_id",
            (run_id,),
        ).fetchall()
        findings = []
        for fr in finding_rows:
            score = effective_score(fr)
            findings.append(
                FindingView(
                    disclosure_id=fr["disclosure_id"],
                    standard=fr["standard"],
                    status=fr["status"],
                    score=score,
                    na_reason=fr["na_reason"],
                    note=fr["note"],
                    evidence_excerpt=fr["evidence_excerpt"],
                    evidence_page=fr["evidence_page"],
                    elements=json.loads(fr["elements_json"]),
                    suggested_fix=fr["suggested_fix"],
                    vision_fallback_used=bool(fr["vision_fallback_used"]),
                )
            )
        corr_rows = conn.execute(
            "SELECT * FROM assessor_corrections "
            "WHERE run_id=%s AND superseded=FALSE ORDER BY disclosure_id",
            (run_id,),
        ).fetchall()
        corrections = [_row_to_correction(r) for r in corr_rows]
        parent_ver = None
        if run["parent_run_id"]:
            p = conn.execute(
                "SELECT version_number FROM runs WHERE id=%s", (run["parent_run_id"],)
            ).fetchone()
            parent_ver = p["version_number"] if p else None
        return RunDetail(
            summary=summary,
            findings=findings,
            corrections=corrections,
            report_id=run["report_id"],
            version_number=run["version_number"],
            kind=run["kind"],
            parent_run_id=run["parent_run_id"],
            parent_version_number=parent_ver,
        ).model_dump()


@router.get("/{run_id}/pdf")
def get_run_pdf(
    run_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    """Stream the source PDF for a run so the evidence viewer can render it."""
    with _open_conn(settings) as conn:
        assert_run_access(conn, run_id, user)
        row = conn.execute(
            "SELECT pdf_path, pdf_filename FROM runs WHERE id=%s", (run_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Run not found")
    path = resolve_pdf_path(row["pdf_path"], settings)
    if not path.is_file():
        raise HTTPException(404, "Source PDF is no longer available")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=row["pdf_filename"],
        content_disposition_type="inline",
    )


@router.delete("/{run_id}", status_code=204)
def delete_run(
    run_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    with _open_conn(settings) as conn:
        assert_run_access(conn, run_id, user)
        row = conn.execute("SELECT id, pdf_path FROM runs WHERE id=%s", (run_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Run not found")

        pdf_path = row["pdf_path"]
        # Cascade (ON DELETE CASCADE on chunks, findings, judge_traces,
        # assessor_corrections) cleans up all child rows in one transaction.
        with conn.transaction():
            conn.execute("DELETE FROM runs WHERE id=%s", (run_id,))

        still_used = conn.execute(
            "SELECT 1 FROM runs WHERE pdf_path=%s LIMIT 1", (pdf_path,)
        ).fetchone()
        if not still_used:
            try:
                Path(pdf_path).unlink(missing_ok=True)
            except OSError:
                pass
    return Response(status_code=204)


_IN_PROGRESS_STATUSES = {"queued", "extracting", "indexing", "judging"}


@router.post("/{run_id}/retry", status_code=201)
def retry_run(
    run_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
    payload: RetryRequest | None = None,
):
    """Create a new version of this run with kind='retry'.

    Copies chunks/vectors/FTS from the source; kicks the judge graph on the
    new run. Does NOT mutate the source — old findings are preserved. An
    optional `disclosure_ids` body overrides which disclosures the new version
    judges; when omitted, it inherits the source run's selection.
    """
    from accordance.api.versioning import _create_versioned_run

    override = None
    if payload is not None and payload.disclosure_ids is not None:
        override = _parse_disclosure_ids(json.dumps(payload.disclosure_ids))
    with _open_conn(settings) as conn:
        assert_run_access(conn, run_id, user)
    new_id, ver = _create_versioned_run(
        settings,
        source_run_id=run_id,
        kind="retry",
        disclosure_ids_override=override,
        acting_user_id=user["id"],
    )
    return {"run_id": new_id, "version_number": ver}


@router.post("/{run_id}/stop", status_code=202)
def stop_run(
    run_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[dict, Depends(require_user)],
):
    """Request cancellation of an in-progress run.

    Sets a process-wide cooperative cancellation flag. In-flight LLM calls
    and Docling extraction finish naturally (we can't safely kill them),
    but no further judge calls start. The DB row is flipped to 'cancelled'
    immediately so the dashboard reflects the action.
    """
    with _open_conn(settings) as conn:
        assert_run_access(conn, run_id, user)
        row = conn.execute("SELECT status FROM runs WHERE id=%s", (run_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Run not found")
        if row["status"] not in _IN_PROGRESS_STATUSES:
            raise HTTPException(
                409,
                f"Cannot stop a run that is already '{row['status']}'.",
            )
        cancel_registry.cancel(run_id)
        conn.execute(
            "UPDATE runs SET status=%s, completed_at=CURRENT_TIMESTAMP WHERE id=%s",
            ("cancelled", run_id),
        )

    from accordance.api.events import bus

    bus.publish(run_id, {"type": "cancelled"})
    return {"run_id": run_id, "status": "cancelled"}
