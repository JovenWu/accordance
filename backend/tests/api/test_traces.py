"""Tests for GET /api/runs/{run_id}/traces."""

import json

from fastapi.testclient import TestClient

from accordance.auth.passwords import hash_password
from accordance.config import get_settings
from accordance.db import connection as db_conn
from accordance.main import create_app


def _login(client):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) "
            "ON CONFLICT (username) DO NOTHING",
            ("tester", hash_password("pw")),
        )
    client.post("/api/auth/login", json={"username": "tester", "password": "pw"})


def _setup_run(tmp_path):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) "
            "ON CONFLICT (username) DO NOTHING",
            ("tester", hash_password("pw")),
        )
        uid = conn.execute("SELECT id FROM users WHERE username='tester'").fetchone()["id"]
        conn.execute(
            "INSERT INTO reports (id, name, created_by) VALUES (%s, %s, %s)",
            ("rep-traces-1", "x.pdf", uid),
        )
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                "r-test",
                "rep-traces-1",
                1,
                "initial",
                "x.pdf",
                "sha-x",
                str(tmp_path / "x.pdf"),
                "completed",
                uid,
            ),
        )


def _insert_trace(
    run_id: str,
    disclosure_id: str,
    attempt: int = 1,
    rejudged: bool = False,
    parse_path: str = "structured",
    evidence_verified: bool | None = True,
):
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO judge_traces
                (run_id, disclosure_id, attempt, rejudged, prompt_hash, model,
                 queries_json, chunk_ids_json, distances_json, pages_json,
                 parse_path, error, latency_ms, evidence_verified)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                disclosure_id,
                attempt,
                rejudged,
                "abc123def4567890",
                "claude-sonnet-4-6",
                json.dumps(["legal name", "headquarters"]),
                json.dumps([10, 11, 12]),
                json.dumps([0.1, 0.15, 0.2]),
                json.dumps([4, 5, 5]),
                parse_path,
                None,
                1234,
                evidence_verified,
            ),
        )


def test_traces_endpoint_returns_grouped_attempts(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    get_settings.cache_clear()

    _setup_run(tmp_path)
    _insert_trace("r-test", "2-1")
    _insert_trace("r-test", "305-1", attempt=1)
    _insert_trace("r-test", "305-1", attempt=2, rejudged=True)

    client = TestClient(create_app())
    _login(client)
    r = client.get("/api/runs/r-test/traces")
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == "r-test"
    assert len(body["traces"]) == 2

    by_id = {t["disclosure_id"]: t for t in body["traces"]}
    assert "2-1" in by_id
    assert "305-1" in by_id

    # 2-1 has one attempt
    assert len(by_id["2-1"]["attempts"]) == 1
    a = by_id["2-1"]["attempts"][0]
    assert a["attempt"] == 1
    assert a["rejudged"] is False
    assert a["parse_path"] == "structured"
    assert a["queries"] == ["legal name", "headquarters"]
    assert a["chunk_ids"] == [10, 11, 12]
    assert a["pages"] == [4, 5, 5]
    assert a["model"] == "claude-sonnet-4-6"
    assert a["evidence_verified"] is True

    # 305-1 has two attempts ordered by attempt #, second is rejudged
    attempts = by_id["305-1"]["attempts"]
    assert [a["attempt"] for a in attempts] == [1, 2]
    assert attempts[0]["rejudged"] is False
    assert attempts[1]["rejudged"] is True


def test_traces_endpoint_404_for_unknown_run(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    get_settings.cache_clear()

    client = TestClient(create_app())
    _login(client)
    r = client.get("/api/runs/does-not-exist/traces")
    assert r.status_code == 404


def test_traces_endpoint_empty_traces_for_run_without_judgments(tmp_path, monkeypatch):
    """Run exists but no trace rows yet (e.g., still in extracting/indexing)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    get_settings.cache_clear()

    _setup_run(tmp_path)

    client = TestClient(create_app())
    _login(client)
    r = client.get("/api/runs/r-test/traces")
    assert r.status_code == 200
    body = r.json()
    assert body["traces"] == []


def test_traces_endpoint_carries_evidence_verified_none(tmp_path, monkeypatch):
    """NULL evidence_verified (LLM returned no excerpt) round-trips as None."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    get_settings.cache_clear()

    _setup_run(tmp_path)
    _insert_trace("r-test", "2-7", evidence_verified=None)

    client = TestClient(create_app())
    _login(client)
    body = client.get("/api/runs/r-test/traces").json()
    assert body["traces"][0]["attempts"][0]["evidence_verified"] is None
