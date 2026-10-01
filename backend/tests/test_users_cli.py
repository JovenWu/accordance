import pytest

from accordance.auth.passwords import verify_password
from accordance.db import connection as db_conn
from accordance.users import add_user, list_users, set_active


def test_add_user_stores_hash():
    with db_conn() as conn:
        add_user(conn, "alice", "pw")
        row = conn.execute(
            "SELECT password_hash, is_active FROM users WHERE username='alice'"
        ).fetchone()
    assert row["is_active"] is True
    assert verify_password("pw", row["password_hash"])
    assert row["password_hash"] != "pw"


def test_add_duplicate_refused():
    with db_conn() as conn:
        add_user(conn, "alice", "pw")
        with pytest.raises(ValueError):
            add_user(conn, "alice", "other")


def test_disable_user():
    with db_conn() as conn:
        add_user(conn, "alice", "pw")
        assert set_active(conn, "alice", False) is True
        assert conn.execute(
            "SELECT is_active FROM users WHERE username='alice'"
        ).fetchone()["is_active"] is False


def test_list_users():
    with db_conn() as conn:
        add_user(conn, "alice", "pw")
        add_user(conn, "bob", "pw")
        names = {u["username"] for u in list_users(conn)}
    assert names == {"alice", "bob"}


def test_set_password_changes_hash():
    from accordance.auth.passwords import verify_password
    from accordance.db import connection
    from accordance.users import add_user, set_password

    with connection() as conn:
        uid = add_user(conn, "pwtarget", "password1")
        assert set_password(conn, uid, "brandnew9") is True
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id=%s", (uid,)
        ).fetchone()
        assert verify_password("brandnew9", row["password_hash"]) is True
        assert verify_password("password1", row["password_hash"]) is False
        assert set_password(conn, 999999, "whatever9") is False
