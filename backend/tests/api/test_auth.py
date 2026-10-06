from fastapi.testclient import TestClient

from accordance.auth.deps import COOKIE_NAME
from accordance.auth.passwords import hash_password
from accordance.config import get_settings
from accordance.db import connection as db_conn
from accordance.main import create_app


def _seed_user(tmp_path, monkeypatch, username="alice", pw="pw", active=True):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    get_settings.cache_clear()
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, is_active) VALUES (%s, %s, %s)",
            (username, hash_password(pw), active),
        )


def test_login_sets_cookie_and_me_returns_user(tmp_path, monkeypatch):
    _seed_user(tmp_path, monkeypatch)
    c = TestClient(create_app())
    r = c.post("/api/auth/login", json={"username": "alice", "password": "pw"})
    assert r.status_code == 200
    assert COOKIE_NAME in r.cookies
    me = c.get("/api/auth/me")
    assert me.status_code == 200 and me.json() == {"username": "alice", "is_admin": False}


def test_login_wrong_password_401(tmp_path, monkeypatch):
    _seed_user(tmp_path, monkeypatch)
    c = TestClient(create_app())
    r = c.post("/api/auth/login", json={"username": "alice", "password": "WRONG"})
    assert r.status_code == 401


def test_login_disabled_user_401(tmp_path, monkeypatch):
    _seed_user(tmp_path, monkeypatch, active=False)
    c = TestClient(create_app())
    r = c.post("/api/auth/login", json={"username": "alice", "password": "pw"})
    assert r.status_code == 401


def test_me_without_login_401(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    assert TestClient(create_app()).get("/api/auth/me").status_code == 401


def test_logout_invalidates_session(tmp_path, monkeypatch):
    _seed_user(tmp_path, monkeypatch)
    c = TestClient(create_app())
    c.post("/api/auth/login", json={"username": "alice", "password": "pw"})
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/auth/me").status_code == 401


def test_me_returns_is_admin_false_for_regular_user(auth_client):
    r = auth_client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json() == {"username": "tester", "is_admin": False}
