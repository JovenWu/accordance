"""Per-user in-flight run quota (caps thread spawn + runaway LLM spend)."""

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from accordance.api.runs import _enforce_run_quota
from accordance.auth.passwords import hash_password
from accordance.config import Settings, get_settings
from accordance.db import connection
from accordance.main import create_app

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_report.pdf"


def _seed(conn, *, inflight=0, completed=0):
    row = conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id",
        ("u", "h"),
    ).fetchone()
    user_id = row["id"]
    conn.execute("INSERT INTO reports (id, name) VALUES (%s, %s)", ("rep1", "r"))
    ver = 0
    for status, count in (("queued", inflight), ("completed", completed)):
        for _ in range(count):
            ver += 1
            conn.execute(
                "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
                "pdf_sha256, pdf_path, status, created_by) "
                "VALUES (%s, %s, %s, 'initial', 'f.pdf', %s, '/x', %s, %s)",
                (f"run{ver}", "rep1", ver, f"sha{ver}", status, user_id),
            )
    return user_id


def test_quota_blocks_at_limit():
    with connection() as conn:
        user_id = _seed(conn, inflight=3)
        with pytest.raises(HTTPException) as exc:
            _enforce_run_quota(conn, user_id, Settings(max_inflight_runs_per_user=3))
    assert exc.value.status_code == 429


def test_quota_allows_under_limit():
    with connection() as conn:
        user_id = _seed(conn, inflight=2)
        _enforce_run_quota(conn, user_id, Settings(max_inflight_runs_per_user=3))  # no raise


def test_quota_ignores_terminal_runs():
    with connection() as conn:
        user_id = _seed(conn, inflight=1, completed=9)
        _enforce_run_quota(conn, user_id, Settings(max_inflight_runs_per_user=3))  # no raise


def test_quota_disabled_when_zero():
    with connection() as conn:
        user_id = _seed(conn, inflight=10)
        _enforce_run_quota(conn, user_id, Settings(max_inflight_runs_per_user=0))  # no raise


def test_create_run_returns_429_over_quota(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("MAX_INFLIGHT_RUNS_PER_USER", "3")

    get_settings.cache_clear()
    with connection() as conn:
        row = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id",
            ("tester", hash_password("pw")),
        ).fetchone()
        uid = row["id"]
        conn.execute("INSERT INTO reports (id, name) VALUES (%s, %s)", ("rep1", "r"))
        for i in range(3):  # fill the quota with in-flight runs
            conn.execute(
                "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
                "pdf_sha256, pdf_path, status, created_by) "
                "VALUES (%s, %s, %s, 'initial', 'f.pdf', %s, '/x', 'queued', %s)",
                (f"run{i}", "rep1", i + 1, f"sha{i}", uid),
            )

    client = TestClient(create_app())
    client.post("/api/auth/login", json={"username": "tester", "password": "pw"})
    with FIXTURE.open("rb") as f:
        r = client.post("/api/runs", files={"pdf": ("a.pdf", f, "application/pdf")})
    assert r.status_code == 429
