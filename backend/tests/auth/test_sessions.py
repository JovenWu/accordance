import hashlib
import time

from accordance.auth.passwords import hash_password
from accordance.auth.sessions import (
    create_session,
    delete_session,
    purge_expired,
    user_for_token,
)
from accordance.db import connection as db_conn


def _seed_user(conn, username="alice", active=True):
    row = conn.execute(
        "INSERT INTO users (username, password_hash, is_active) VALUES (%s, %s, %s) RETURNING id",
        (username, hash_password("pw"), active),
    ).fetchone()
    return row["id"]


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def test_create_and_lookup():
    with db_conn() as conn:
        uid = _seed_user(conn)
        tok = create_session(conn, uid, ttl_days=1)
        u = user_for_token(conn, tok)
    assert u is not None and u["username"] == "alice" and u["id"] == uid


def test_expired_token_rejected():
    with db_conn() as conn:
        uid = _seed_user(conn)
        tok = create_session(conn, uid, ttl_days=1)
        conn.execute(
            "UPDATE sessions SET expires_at=%s WHERE user_id=%s",
            (int(time.time()) - 10, uid),
        )
        assert user_for_token(conn, tok) is None


def test_deleted_token_rejected():
    with db_conn() as conn:
        uid = _seed_user(conn)
        tok = create_session(conn, uid, ttl_days=1)
        delete_session(conn, tok)
        assert user_for_token(conn, tok) is None


def test_disabled_user_token_rejected():
    with db_conn() as conn:
        uid = _seed_user(conn, active=True)
        tok = create_session(conn, uid, ttl_days=1)
        conn.execute("UPDATE users SET is_active=FALSE WHERE id=%s", (uid,))
        assert user_for_token(conn, tok) is None


def test_purge_expired_removes_only_expired():
    with db_conn() as conn:
        uid = _seed_user(conn)
        live = create_session(conn, uid, ttl_days=1)
        dead = create_session(conn, uid, ttl_days=1)
        conn.execute(
            "UPDATE sessions SET expires_at=%s WHERE token_hash=%s",
            (int(time.time()) - 10, _hash_token(dead)),
        )
        assert purge_expired(conn) == 1
        assert user_for_token(conn, live) is not None
        assert user_for_token(conn, dead) is None


def test_user_for_token_returns_is_admin():
    with db_conn() as conn:
        row = conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES ('boss','h',TRUE) RETURNING id"
        ).fetchone()
        uid = row["id"]
        tok = create_session(conn, uid, ttl_days=1)
        user = user_for_token(conn, tok)
    assert user["is_admin"] is True
