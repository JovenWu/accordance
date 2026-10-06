"""Tests for SystemConfig population from DB + rendering in the report."""

import json

from accordance import db
from accordance.config import get_settings
from accordance.eval.metrics import SystemConfig, compute_eval
from accordance.eval.report import render_markdown
from accordance.eval.runner import _load_system_config
from accordance.eval.schema import GroundTruth, LabeledDisclosure
from accordance.models import FindingView


def _setup_db():
    get_settings.cache_clear()
    s = get_settings()
    conn = db.connect_direct(s)
    db.ensure_schema(conn)
    db.ensure_embedding_dim(conn, dim=8)
    conn.execute(
        "TRUNCATE reports, runs, chunks, findings, judge_traces, "
        "assessor_corrections, llm_usage, run_completions, users, sessions "
        "RESTART IDENTITY CASCADE"
    )
    conn.execute(
        "INSERT INTO reports (id, name) VALUES (%s, %s)",
        ("rep-sc-1", "x.pdf"),
    )
    conn.execute(
        "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, pdf_sha256, pdf_path, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        ("r1", "rep-sc-1", 1, "initial", "x.pdf", "sha", "x", "completed"),
    )
    return conn


def _insert_finding(
    conn,
    disclosure_id: str,
    prompt_hash: str = "abc12345def67890",
    vision: bool = False,
):
    conn.execute(
        """
        INSERT INTO findings
            (run_id, disclosure_id, standard, status, note, evidence_excerpt,
             evidence_page, elements_json, suggested_fix, vision_fallback_used,
             prompt_hash)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            "r1",
            disclosure_id,
            "GRI 2",
            "covered",
            "ok",
            None,
            None,
            "[]",
            "fix",
            vision,
            prompt_hash,
        ),
    )


def _insert_trace(
    conn,
    disclosure_id: str,
    attempt: int = 1,
    rejudged: bool = False,
    parse_path: str = "structured",
    evidence_verified: bool | None = True,
    model: str = "claude-sonnet-4-6",
    prompt_hash: str = "abc12345def67890",
):
    conn.execute(
        """
        INSERT INTO judge_traces
            (run_id, disclosure_id, attempt, rejudged, prompt_hash, model,
             queries_json, chunk_ids_json, distances_json, pages_json,
             parse_path, error, latency_ms, evidence_verified)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            "r1",
            disclosure_id,
            attempt,
            rejudged,
            prompt_hash,
            model,
            json.dumps([]),
            json.dumps([]),
            json.dumps([]),
            json.dumps([]),
            parse_path,
            None,
            1234,
            evidence_verified,
        ),
    )


def test_load_system_config_aggregates_counts():
    conn = _setup_db()
    try:
        _insert_finding(conn, "2-1")
        _insert_finding(conn, "305-1", vision=True)
        _insert_finding(conn, "303-3")

        _insert_trace(conn, "2-1")
        _insert_trace(conn, "305-1", attempt=1)
        _insert_trace(conn, "305-1", attempt=2, rejudged=True, evidence_verified=False)
        _insert_trace(conn, "303-3", parse_path="fallback", evidence_verified=None)

        sc = _load_system_config(conn, "r1")
        assert sc.prompt_hashes == ["abc12345def67890"]
        assert sc.models == ["claude-sonnet-4-6"]
        assert sc.total_traces == 4
        assert sc.rejudge_count == 1
        assert sc.vision_fallback_count == 1
        assert sc.hallucinated_cleared_count == 1
        assert sc.no_excerpt_count == 1
        assert sc.parse_fallback_count == 1
        assert sc.parse_error_count == 0
        assert sc.retrieval_mode == "hybrid"
        assert sc.retrieval_per_element is True
    finally:
        conn.close()


def test_load_system_config_dedups_multiple_prompt_hashes():
    """A run that was partially retried after a prompt change would carry
    multiple prompt_hash values — surface them all."""
    conn = _setup_db()
    try:
        _insert_finding(conn, "2-1", prompt_hash="aaaaaaaaaaaaaaaa")
        _insert_finding(conn, "2-2", prompt_hash="bbbbbbbbbbbbbbbb")
        _insert_finding(conn, "2-3", prompt_hash="aaaaaaaaaaaaaaaa")
        sc = _load_system_config(conn, "r1")
        assert sc.prompt_hashes == ["aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"]
    finally:
        conn.close()


def test_load_system_config_empty_for_unjudged_run():
    conn = _setup_db()
    try:
        sc = _load_system_config(conn, "r1")
        assert sc.total_traces == 0
        assert sc.prompt_hashes == []
        assert sc.models == []
    finally:
        conn.close()


def test_render_markdown_includes_system_config_section():
    gt = GroundTruth(
        report_id="demo",
        pdf_filename="x.pdf",
        disclosures=[LabeledDisclosure(id="2-1", expected_status="covered")],
    )
    findings = [
        FindingView(
            disclosure_id="2-1",
            standard="GRI 2",
            status="covered",
            note="ok",
            evidence_excerpt=None,
            evidence_page=None,
            elements=[],
            suggested_fix="-",
            vision_fallback_used=False,
        )
    ]
    report = compute_eval(gt, findings)
    report.system_config = SystemConfig(
        prompt_hashes=["abc12345def67890"],
        models=["claude-sonnet-4-6"],
        total_traces=10,
        rejudge_count=3,
        vision_fallback_count=2,
        hallucinated_cleared_count=1,
        no_excerpt_count=4,
        parse_fallback_count=0,
        parse_error_count=0,
    )
    md = render_markdown(report)
    assert "## System Config" in md
    assert "`abc12345`" in md
    assert "claude-sonnet-4-6" in md
    assert "Total judge calls" in md
    assert "Re-judges fired" in md
    assert "Vision fallbacks used" in md


def test_render_markdown_omits_system_config_section_when_none():
    gt = GroundTruth(
        report_id="demo",
        pdf_filename="x.pdf",
        disclosures=[LabeledDisclosure(id="2-1", expected_status="covered")],
    )
    findings = [
        FindingView(
            disclosure_id="2-1",
            standard="GRI 2",
            status="covered",
            note="ok",
            evidence_excerpt=None,
            evidence_page=None,
            elements=[],
            suggested_fix="-",
            vision_fallback_used=False,
        )
    ]
    report = compute_eval(gt, findings)
    md = render_markdown(report)
    assert "## System Config" not in md
