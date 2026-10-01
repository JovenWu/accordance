from accordance.auth.passwords import verify_password
from accordance.config import Settings
from accordance.db import connection as db_conn
from accordance.users import add_user, bootstrap_admin, set_admin


def test_add_user_admin_flag():
    with db_conn() as conn:
        add_user(conn, "boss", "password1", is_admin=True)
        row = conn.execute("SELECT is_admin FROM users WHERE username='boss'").fetchone()
    assert row["is_admin"] is True


def test_set_admin_toggles():
    with db_conn() as conn:
        add_user(conn, "u", "password1")
        assert set_admin(conn, "u", True) is True
        assert conn.execute(
            "SELECT is_admin FROM users WHERE username='u'"
        ).fetchone()["is_admin"] is True
        set_admin(conn, "u", False)
        assert conn.execute(
            "SELECT is_admin FROM users WHERE username='u'"
        ).fetchone()["is_admin"] is False
        assert set_admin(conn, "ghost", True) is False


def test_bootstrap_creates_admin():
    with db_conn() as conn:
        s = Settings(admin_username="root", admin_password="supersecret")
        assert bootstrap_admin(conn, s) == "created"
        row = conn.execute(
            "SELECT is_admin, is_active FROM users WHERE username='root'"
        ).fetchone()
    assert row["is_admin"] is True and row["is_active"] is True


def test_bootstrap_promotes_existing_without_touching_password():
    with db_conn() as conn:
        add_user(conn, "root", "oldpassword")
        old_hash = conn.execute(
            "SELECT password_hash FROM users WHERE username='root'"
        ).fetchone()["password_hash"]
        conn.execute("UPDATE users SET is_admin=FALSE, is_active=FALSE WHERE username='root'")
        s = Settings(admin_username="root", admin_password="")
        assert bootstrap_admin(conn, s) == "promoted"
        row = conn.execute(
            "SELECT is_admin, is_active, password_hash FROM users WHERE username='root'"
        ).fetchone()
    assert row["is_admin"] is True and row["is_active"] is True
    assert row["password_hash"] == old_hash  # empty ADMIN_PASSWORD leaves it alone


def test_bootstrap_skips_missing_user_without_password():
    with db_conn() as conn:
        s = Settings(admin_username="ghost", admin_password="")
        assert bootstrap_admin(conn, s) == "skipped"
        assert conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0


def test_bootstrap_noop_without_username():
    with db_conn() as conn:
        assert bootstrap_admin(conn, Settings(admin_username="")) is None


def test_bootstrap_promotes_existing_and_rotates_password():
    with db_conn() as conn:
        add_user(conn, "root", "oldpassword")
        s = Settings(admin_username="root", admin_password="newpassword1")
        assert bootstrap_admin(conn, s) == "promoted"
        row = conn.execute(
            "SELECT is_admin, is_active, password_hash FROM users WHERE username='root'"
        ).fetchone()
    assert row["is_admin"] is True and row["is_active"] is True
    assert verify_password("newpassword1", row["password_hash"]) is True
    assert verify_password("oldpassword", row["password_hash"]) is False
