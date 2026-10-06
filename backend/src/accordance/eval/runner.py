"""Eval runner: resolve PDF + run, invoke pipeline if needed, return EvalReport.

This is the bridge between the pure-function metrics and the rest of the
system (DB + pipeline). The CLI wraps it; tests can call it with mocks.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from pathlib import Path

import psycopg

from accordance.config import Settings, embedding_credentials, get_settings
from accordance.db import connect_direct, ensure_embedding_dim, ensure_schema
from accordance.eval.metrics import EvalReport, SystemConfig, compute_eval
from accordance.eval.schema import GroundTruth
from accordance.indexer.embedder import build_embedder, embedding_dim
from accordance.judge.output_schema import ElementJudgment
from accordance.judge.rollup import effective_score
from accordance.kb.loader import load_kb
from accordance.llm.adapter import build_llm
from accordance.models import FindingView

KB_DIR = Path(__file__).resolve().parents[4] / "kb" / "gri"


def _open_conn(settings: Settings):
    conn = connect_direct(settings)
    ensure_schema(conn)
    ensure_embedding_dim(conn, dim=embedding_dim(settings.embedding_model))
    return conn


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _find_run_by_sha(conn: psycopg.Connection, sha: str) -> str | None:
    row = conn.execute("SELECT id, status FROM runs WHERE pdf_sha256=%s", (sha,)).fetchone()
    if row is None:
        return None
    if row["status"] in ("completed", "cancelled"):
        return row["id"]
    return None


def _find_run_by_filename(conn: psycopg.Connection, filename: str) -> str | None:
    row = conn.execute(
        "SELECT id FROM runs WHERE pdf_filename=%s AND status='completed' "
        "ORDER BY uploaded_at DESC LIMIT 1",
        (filename,),
    ).fetchone()
    return row["id"] if row else None


def _load_system_config(
    conn: psycopg.Connection,
    run_id: str,
    settings: Settings | None = None,
) -> SystemConfig:
    """Summarize the run's system config from findings + judge_traces.

    Eval reports rely on this to attribute accuracy deltas. If two reports
    have different prompt_hashes, retrieval modes, or rejudge counts, the
    delta is explainable by config rather than randomness.
    """
    if settings is None:
        settings = get_settings()
    prompt_rows = conn.execute(
        "SELECT DISTINCT prompt_hash FROM findings WHERE run_id=%s AND prompt_hash IS NOT NULL",
        (run_id,),
    ).fetchall()
    prompt_hashes = sorted({r["prompt_hash"] for r in prompt_rows})

    vision_row = conn.execute(
        "SELECT COUNT(*) AS n FROM findings WHERE run_id=%s AND vision_fallback_used=TRUE",
        (run_id,),
    ).fetchone()
    vision_count = vision_row["n"] if vision_row else 0

    model_rows = conn.execute(
        "SELECT DISTINCT model FROM judge_traces WHERE run_id=%s", (run_id,)
    ).fetchall()
    models = sorted({r["model"] for r in model_rows})

    counts_row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN rejudged=TRUE THEN 1 ELSE 0 END) AS rejudge,
            SUM(CASE WHEN evidence_verified=FALSE THEN 1 ELSE 0 END) AS halluc,
            SUM(CASE WHEN evidence_verified IS NULL THEN 1 ELSE 0 END) AS no_excerpt,
            SUM(CASE WHEN parse_path='fallback' THEN 1 ELSE 0 END) AS parse_fb,
            SUM(CASE WHEN parse_path='error' THEN 1 ELSE 0 END) AS parse_err
        FROM judge_traces WHERE run_id=%s
        """,
        (run_id,),
    ).fetchone()

    return SystemConfig(
        prompt_hashes=prompt_hashes,
        models=models,
        total_traces=(counts_row["total"] if counts_row else 0) or 0,
        rejudge_count=(counts_row["rejudge"] if counts_row else 0) or 0,
        vision_fallback_count=vision_count or 0,
        hallucinated_cleared_count=(counts_row["halluc"] if counts_row else 0) or 0,
        no_excerpt_count=(counts_row["no_excerpt"] if counts_row else 0) or 0,
        parse_fallback_count=(counts_row["parse_fb"] if counts_row else 0) or 0,
        parse_error_count=(counts_row["parse_err"] if counts_row else 0) or 0,
        retrieval_mode=settings.retrieval_mode,
        retrieval_per_element=settings.retrieval_per_element,
        rerank_enabled=settings.rerank_enabled,
        rerank_model=settings.rerank_model,
        rerank_top_n=settings.rerank_top_n,
    )


def _load_retrieved_pages(conn: psycopg.Connection, run_id: str) -> dict[str, set[int]]:
    """Union of pages the judge actually saw, per disclosure, from judge_traces."""
    rows = conn.execute(
        "SELECT disclosure_id, pages_json FROM judge_traces WHERE run_id=%s",
        (run_id,),
    ).fetchall()
    out: dict[str, set[int]] = {}
    for r in rows:
        try:
            pages = json.loads(r["pages_json"])
            if not isinstance(pages, list):
                pages = []
            out.setdefault(r["disclosure_id"], set()).update(int(p) for p in pages if p is not None)
        except (TypeError, ValueError):
            pass
    return out


def _load_findings(
    conn: psycopg.Connection, run_id: str, only: Iterable[str] | None = None
) -> list[FindingView]:
    rows = conn.execute(
        "SELECT * FROM findings WHERE run_id=%s ORDER BY disclosure_id", (run_id,)
    ).fetchall()
    out: list[FindingView] = []
    keep = set(only) if only else None
    for fr in rows:
        if keep is not None and fr["disclosure_id"] not in keep:
            continue
        elements_raw = json.loads(fr["elements_json"])
        elements = [ElementJudgment.model_validate(e) for e in elements_raw]
        out.append(
            FindingView(
                disclosure_id=fr["disclosure_id"],
                standard=fr["standard"],
                status=fr["status"],
                score=effective_score(fr),
                na_reason=fr["na_reason"],
                note=fr["note"],
                evidence_excerpt=fr["evidence_excerpt"],
                evidence_page=fr["evidence_page"],
                elements=elements,
                suggested_fix=fr["suggested_fix"],
                vision_fallback_used=bool(fr["vision_fallback_used"]),
            )
        )
    return out


def _resolve_pdf_path(gt: GroundTruth, gt_file: Path) -> Path | None:
    """Try to locate the PDF for a ground-truth file.

    Priority:
      1. gt.pdf_path (resolved relative to the YAML file).
      2. Look in settings.pdf_dir for a file whose sha matches gt.pdf_sha256.
      3. Look for a file whose name matches gt.pdf_filename.

    Returns None if no candidate exists — caller decides whether that's
    fatal (need to re-run) or fine (have a matching completed run).
    """
    if gt.pdf_path:
        p = (gt_file.parent / gt.pdf_path).resolve()
        if p.exists():
            return p
    settings = get_settings()
    pdf_dir = settings.pdf_dir
    if pdf_dir.exists() and gt.pdf_sha256:
        for candidate in pdf_dir.glob("*.pdf"):
            if _sha256_file(candidate) == gt.pdf_sha256:
                return candidate
    if pdf_dir.exists():
        cand = pdf_dir / gt.pdf_filename
        if cand.exists():
            return cand
    return None


def _run_pipeline_sync(
    pdf_path: Path,
    settings: Settings,
    conn: psycopg.Connection,
    *,
    rerun: bool = False,
) -> str:
    """Create a new run row and invoke the LangGraph pipeline synchronously.

    Returns the run_id. Raises on pipeline failure (the run row will be
    left in whatever state the pipeline put it in).
    """
    from accordance.graph.build import run_graph

    sha = _sha256_file(pdf_path)

    if not rerun:
        existing = _find_run_by_sha(conn, sha)
        if existing:
            return existing

    run_id = str(uuid.uuid4())
    settings.pdf_dir.mkdir(parents=True, exist_ok=True)
    stored_pdf = settings.pdf_dir / f"{run_id}.pdf"
    if stored_pdf.resolve() != pdf_path.resolve():
        stored_pdf.write_bytes(pdf_path.read_bytes())

    report_id = "rep-" + run_id[:8]
    conn.execute(
        "INSERT INTO reports (id, name) VALUES (%s, %s)",
        (report_id, pdf_path.name),
    )
    conn.execute(
        "INSERT INTO runs (id, report_id, version_number, kind, "
        "pdf_filename, pdf_sha256, pdf_path, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (run_id, report_id, 1, "initial", pdf_path.name, sha, str(stored_pdf), "queued"),
    )

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
        pdf_path=stored_pdf,
        kb=kb,
        conn=conn,
        embedder=embedder,
        llm=llm,
        retrieval_mode=settings.retrieval_mode,
    )
    return run_id


def evaluate(
    gt_path: Path,
    *,
    use_run: str | None = None,
    rerun: bool = False,
    only: list[str] | None = None,
    settings: Settings | None = None,
) -> EvalReport:
    """Score a ground-truth file against the pipeline's output.

    Resolution order:
      - `use_run`: caller specified an explicit run_id.
      - else find an existing completed run by pdf_sha256 (skipped if --rerun).
      - else find an existing completed run by pdf_filename (skipped if --rerun).
      - else run the pipeline fresh on the resolved PDF path.

    `only` filters comparison + (when running) does NOT filter judging itself —
    the pipeline always judges all 38 disclosures; we just narrow the score.
    """
    settings = settings or get_settings()
    gt = GroundTruth.from_yaml(gt_path)
    conn = _open_conn(settings)
    try:
        if use_run:
            row = conn.execute("SELECT id FROM runs WHERE id=%s", (use_run,)).fetchone()
            if not row:
                raise FileNotFoundError(f"Run not found: {use_run}")
            run_id = use_run
        elif not rerun and gt.pdf_sha256 and (run := _find_run_by_sha(conn, gt.pdf_sha256)):
            run_id = run
        elif not rerun and (run := _find_run_by_filename(conn, gt.pdf_filename)):
            run_id = run
        else:
            pdf_path = _resolve_pdf_path(gt, gt_path)
            if pdf_path is None:
                raise FileNotFoundError(
                    f"No PDF found for ground truth {gt.report_id!r}. "
                    f"Set `pdf_path` in the YAML, drop the PDF into "
                    f"{settings.pdf_dir}, or pass --use-run."
                )
            run_id = _run_pipeline_sync(pdf_path, settings, conn, rerun=rerun)

        findings = _load_findings(conn, run_id, only=only)
        if only:
            keep = set(only)
            gt = GroundTruth(
                **{
                    **gt.model_dump(),
                    "disclosures": [d for d in gt.disclosures if d.id in keep],
                }
            )
        retrieved = _load_retrieved_pages(conn, run_id)
        result = compute_eval(gt, findings, run_id=run_id, retrieved_pages_by_disclosure=retrieved)
        result.system_config = _load_system_config(conn, run_id)
        return result
    finally:
        conn.close()
