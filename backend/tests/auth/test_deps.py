from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from accordance.auth.deps import COOKIE_NAME, require_admin, require_user
from accordance.auth.passwords import hash_password
from accordance.auth.sessions import create_session
from accordance.config import get_settings
from accordance.db import connection as db_conn


def _app():
    app = FastAPI()

    @app.get("/whoami")
    def whoami(user=Depends(require_user)):
        return {"username": user["username"]}

    return app


def _seed_session(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    get_settings.cache_clear()
    with db_conn() as conn:
        row = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES ('alice', %s) RETURNING id",
            (hash_password("pw"),),
        ).fetchone()
        uid = row["id"]
        tok = create_session(conn, uid, ttl_days=1)
    return tok


def test_no_cookie_is_401(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    r = TestClient(_app()).get("/whoami")
    assert r.status_code == 401


def test_valid_cookie_is_200(tmp_path, monkeypatch):
    tok = _seed_session(monkeypatch, tmp_path)
    c = TestClient(_app())
    c.cookies.set(COOKIE_NAME, tok)
    r = c.get("/whoami")
    assert r.status_code == 200
    assert r.json() == {"username": "alice"}


def test_garbage_cookie_is_401(tmp_path, monkeypatch):
    _seed_session(monkeypatch, tmp_path)
    c = TestClient(_app())
    c.cookies.set(COOKIE_NAME, "garbage")
    assert c.get("/whoami").status_code == 401


def _admin_app():
    app = FastAPI()

    @app.get("/adminonly")
    def adminonly(user=Depends(require_admin)):
        return {"ok": True}

    return app


def _seed_session_admin(monkeypatch, tmp_path, is_admin):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    get_settings.cache_clear()
    with db_conn() as conn:
        row = conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES ('u', %s, %s) RETURNING id",
            (hash_password("pw"), is_admin),
        ).fetchone()
        uid = row["id"]
        tok = create_session(conn, uid, ttl_days=1)
    return tok


def test_require_admin_allows_admin(tmp_path, monkeypatch):
    tok = _seed_session_admin(monkeypatch, tmp_path, True)
    c = TestClient(_admin_app())
    c.cookies.set(COOKIE_NAME, tok)
    assert c.get("/adminonly").status_code == 200


def test_require_admin_forbids_nonadmin(tmp_path, monkeypatch):
    tok = _seed_session_admin(monkeypatch, tmp_path, False)
    c = TestClient(_admin_app())
    c.cookies.set(COOKIE_NAME, tok)
    assert c.get("/adminonly").status_code == 403
