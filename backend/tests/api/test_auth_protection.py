# backend/tests/api/test_auth_protection.py
from fastapi.testclient import TestClient

from accordance.auth.passwords import hash_password
from accordance.db import connection as db_conn
from accordance.main import create_app


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("LLM_MODEL", "fake:fake")


def test_reports_requires_auth(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    assert TestClient(create_app()).get("/api/reports").status_code == 401


def test_health_stays_public(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    assert TestClient(create_app()).get("/api/health").status_code == 200


def test_reports_ok_after_login(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES ('alice', %s)",
            (hash_password("pw"),),
        )
    c = TestClient(create_app())
    c.post("/api/auth/login", json={"username": "alice", "password": "pw"})
    assert c.get("/api/reports").status_code == 200
