import pytest
from fastapi.testclient import TestClient

from accordance.db import connection
from accordance.main import create_app


def test_startup_reconciles_orphaned_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("LLM_MODEL", "fake:fake")

    with connection() as conn:
        conn.execute("INSERT INTO reports (id, name) VALUES ('rep', 'x.pdf')")
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status) "
            "VALUES ('r1', 'rep', 1, 'initial', 'x.pdf', 'sha1', 'x', 'judging')"
        )
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status) "
            "VALUES ('r2', 'rep', 2, 'retry', 'x.pdf', 'sha2', 'x', 'completed')"
        )

    with TestClient(create_app()) as client:
        assert client.get("/api/health").status_code == 200

        with connection() as conn:
            r1 = conn.execute("SELECT status, error FROM runs WHERE id='r1'").fetchone()
            r2 = conn.execute("SELECT status FROM runs WHERE id='r2'").fetchone()

    assert r1["status"] == "failed"
    assert "restart" in r1["error"].lower()
    assert r2["status"] == "completed"


def test_startup_fails_fast_on_missing_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("LLM_MODEL", "openai:gpt-5-mini")
    monkeypatch.setenv("LLM_API_KEY", "")

    with pytest.raises(RuntimeError):
        with TestClient(create_app()) as client:
            client.get("/api/health")


def test_startup_ok_with_fake_models(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    with TestClient(create_app()) as client:
        assert client.get("/api/health").status_code == 200
