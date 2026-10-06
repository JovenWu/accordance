import pytest
from fastapi import HTTPException

from accordance.api.ownership import (
    assert_report_access,
    assert_run_access,
    visible_reports_clause,
)
from accordance.db import connection


def _mk(conn, uid, rep, run=None):
    conn.execute("INSERT INTO reports (id, name, created_by) VALUES (%s, 'r', %s)", (rep, uid))
    if run:
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status, created_by) VALUES "
            "(%s, %s, 1, 'initial', 'f', 's', 'p', 'completed', %s)",
            (run, rep, uid),
        )


def test_visible_clause_admin_vs_user():
    assert visible_reports_clause({"id": 1, "is_admin": True}) == ("", [])
    clause, params = visible_reports_clause({"id": 7, "is_admin": False})
    assert "created_by = %s" in clause and params == [7]


def test_assert_report_access_owner_ok_others_404():
    with connection() as conn:
        conn.execute("INSERT INTO users (username, password_hash) VALUES ('a', 'x')")
        owner = conn.execute("SELECT id FROM users WHERE username='a'").fetchone()["id"]
        _mk(conn, owner, "rep1")
        assert_report_access(conn, "rep1", {"id": owner, "is_admin": False})
        with pytest.raises(HTTPException) as ei:
            assert_report_access(conn, "rep1", {"id": owner + 999, "is_admin": False})
        assert ei.value.status_code == 404
        assert_report_access(conn, "rep1", {"id": owner + 999, "is_admin": True})


def test_assert_run_access_maps_through_report():
    with connection() as conn:
        conn.execute("INSERT INTO users (username, password_hash) VALUES ('b', 'x')")
        owner = conn.execute("SELECT id FROM users WHERE username='b'").fetchone()["id"]
        _mk(conn, owner, "rep2", "run2")
        assert assert_run_access(conn, "run2", {"id": owner, "is_admin": False}) == "rep2"
        with pytest.raises(HTTPException):
            assert_run_access(conn, "run2", {"id": owner + 999, "is_admin": False})
        assert assert_run_access(conn, "run2", {"id": owner + 999, "is_admin": True}) == "rep2"


def test_assert_report_access_deleted_is_404():
    with connection() as conn:
        conn.execute("INSERT INTO users (username, password_hash) VALUES ('c', 'x')")
        owner = conn.execute("SELECT id FROM users WHERE username='c'").fetchone()["id"]
        conn.execute(
            "INSERT INTO reports (id, name, created_by, deleted_at) VALUES (%s, 'r', %s, NOW())",
            ("rep-del", owner),
        )
        with pytest.raises(HTTPException) as ei:
            assert_report_access(conn, "rep-del", {"id": owner, "is_admin": False})
        assert ei.value.status_code == 404
        with pytest.raises(HTTPException):
            assert_report_access(conn, "rep-del", {"id": owner, "is_admin": True})


def test_assert_access_missing_ids_are_404():
    with connection() as conn:
        conn.execute("INSERT INTO users (username, password_hash) VALUES ('d', 'x')")
        uid = conn.execute("SELECT id FROM users WHERE username='d'").fetchone()["id"]
        for fn, arg in ((assert_report_access, "no-rep"), (assert_run_access, "no-run")):
            with pytest.raises(HTTPException) as ei:
                fn(conn, arg, {"id": uid, "is_admin": False})
            assert ei.value.status_code == 404
