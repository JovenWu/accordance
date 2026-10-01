import pytest

from accordance import db
from accordance.config import get_settings
from accordance.db import SCHEMA_VERSION


@pytest.fixture
def conn():
    get_settings.cache_clear()
    s = get_settings()
    c = db.connect_direct(s)
    db.ensure_schema(c)
    db.ensure_embedding_dim(c, dim=8)
    c.execute(
        "TRUNCATE reports, runs, chunks, findings, judge_traces, "
        "assessor_corrections, llm_usage, run_completions, users, sessions "
        "RESTART IDENTITY CASCADE"
    )
    yield c
    c.close()


def test_ensure_schema_creates_users_and_sessions(conn):
    # users and sessions tables must exist with the expected columns
    cols = {
        r["column_name"]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='users'"
        ).fetchall()
    }
    assert {"id", "username", "password_hash", "is_active", "created_at"} <= cols

    scols = {
        r["column_name"]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='sessions'"
        ).fetchall()
    }
    assert {"token_hash", "user_id", "created_at", "expires_at"} <= scols

    ver = conn.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()["value"]
    assert ver == SCHEMA_VERSION

    # is_active and is_admin must be real BOOLEAN columns
    is_active_type = conn.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name='users' AND column_name='is_active'"
    ).fetchone()["data_type"]
    assert is_active_type == "boolean"

    is_admin_type = conn.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name='users' AND column_name='is_admin'"
    ).fetchone()["data_type"]
    assert is_admin_type == "boolean"
