import getpass

from accordance.db import connection as db_conn
from accordance.users import __main__ as cli


def test_cli_promote_then_demote(monkeypatch):
    with db_conn() as conn:
        conn.execute("INSERT INTO users (username, password_hash) VALUES ('u','h')")

    assert cli.main(["promote", "u"]) == 0
    with db_conn() as conn:
        assert conn.execute(
            "SELECT is_admin FROM users WHERE username='u'"
        ).fetchone()["is_admin"] is True

    assert cli.main(["demote", "u"]) == 0
    with db_conn() as conn:
        assert conn.execute(
            "SELECT is_admin FROM users WHERE username='u'"
        ).fetchone()["is_admin"] is False


def test_cli_add_admin(monkeypatch):
    monkeypatch.setattr(getpass, "getpass", lambda *_a, **_k: "password1")
    assert cli.main(["add", "boss", "--admin"]) == 0
    with db_conn() as conn:
        assert conn.execute(
            "SELECT is_admin FROM users WHERE username='boss'"
        ).fetchone()["is_admin"] is True
