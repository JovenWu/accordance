from fastapi.testclient import TestClient

from accordance.auth.passwords import hash_password
from accordance.config import get_settings
from accordance.db import connection as db_conn
from accordance.main import create_app


def _client(tmp_path, monkeypatch, max_mb: str):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("MAX_UPLOAD_MB", max_mb)
    get_settings.cache_clear()
    client = TestClient(create_app())
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES ('tester', %s) "
            "ON CONFLICT (username) DO NOTHING",
            (hash_password("pw"),),
        )
    client.post("/api/auth/login", json={"username": "tester", "password": "pw"})
    return client


def test_create_run_rejects_oversized_upload(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, max_mb="1")
    big = b"%PDF-1.4\n" + b"0" * (2 * 1024 * 1024)  # ~2 MB, over the 1 MB cap
    r = client.post("/api/runs", files={"pdf": ("big.pdf", big, "application/pdf")})
    assert r.status_code == 413


def test_create_run_accepts_within_limit(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, max_mb="5")
    small = b"%PDF-1.4\n" + b"0" * 1024  # 1 KB, well under the cap
    r = client.post("/api/runs", files={"pdf": ("small.pdf", small, "application/pdf")})
    assert r.status_code != 413  # not rejected for size (kicks off normally)
