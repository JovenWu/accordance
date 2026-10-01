"""Untrusted-upload validation: a non-PDF body must be rejected at the door
(400) before any file is persisted or run rows are created."""
from fastapi.testclient import TestClient

from accordance.auth.passwords import hash_password
from accordance.config import get_settings
from accordance.db import connection as db_conn
from accordance.main import create_app


def _login(client):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES ('tester', %s) "
            "ON CONFLICT (username) DO NOTHING",
            (hash_password("pw"),),
        )
    client.post("/api/auth/login", json={"username": "tester", "password": "pw"})


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    get_settings.cache_clear()
    client = TestClient(create_app())
    _login(client)
    return client


def test_upload_rejects_non_pdf_bytes(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    # octet-stream passes the content-type gate, but the bytes aren't a PDF.
    r = client.post(
        "/api/runs",
        files={"pdf": ("evil.pdf", b"this is not a pdf at all", "application/octet-stream")},
    )
    assert r.status_code == 400
    assert "pdf" in r.json()["detail"].lower()


def test_upload_rejects_non_pdf_does_not_create_run(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    client.post(
        "/api/runs",
        files={"pdf": ("evil.pdf", b"%PNG\x00garbage", "application/octet-stream")},
    )
    # No report/run should have been persisted for the rejected upload.
    with db_conn() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
    assert n == 0


def test_upload_accepts_real_pdf_header(tmp_path, monkeypatch):
    client = _app(tmp_path, monkeypatch)
    # Minimal valid-enough PDF header; extraction may still fail later, but the
    # door check must let a real %PDF- body through (not a 400).
    body = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
    r = client.post(
        "/api/runs",
        files={"pdf": ("ok.pdf", body, "application/pdf")},
    )
    assert r.status_code in (200, 201)
