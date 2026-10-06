"""Login throttling: a client/username is locked out after N failed attempts."""

from fastapi.testclient import TestClient

from accordance.auth.passwords import hash_password
from accordance.config import get_settings
from accordance.db import connection as db_conn
from accordance.main import create_app


def _seed_user():
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES ('tester', %s) "
            "ON CONFLICT (username) DO NOTHING",
            (hash_password("right-pw"),),
        )


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("LOGIN_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("LOGIN_WINDOW_SECONDS", "300")
    get_settings.cache_clear()
    _seed_user()
    return TestClient(create_app())


def test_lockout_after_max_failed_attempts(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    for _ in range(3):
        r = client.post("/api/auth/login", json={"username": "tester", "password": "nope"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"username": "tester", "password": "right-pw"})
    assert r.status_code == 429


def test_successful_login_resets_the_counter(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    for _ in range(2):
        assert client.post(
            "/api/auth/login", json={"username": "tester", "password": "nope"}
        ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"username": "tester", "password": "right-pw"}
    ).status_code == 200
    for _ in range(2):
        assert client.post(
            "/api/auth/login", json={"username": "tester", "password": "nope"}
        ).status_code == 401


def test_throttle_disabled_when_limit_zero(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("LOGIN_MAX_ATTEMPTS", "0")
    get_settings.cache_clear()
    _seed_user()
    client = TestClient(create_app())
    for _ in range(8):
        assert client.post(
            "/api/auth/login", json={"username": "tester", "password": "nope"}
        ).status_code == 401
