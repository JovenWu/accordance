import pytest

from accordance import db
from accordance.config import get_settings


@pytest.fixture
def conn():
    # Uses TEST_DATABASE_URL (or DATABASE_URL) against a real Postgres.
    get_settings.cache_clear()
    s = get_settings()
    c = db.connect_direct(s)
    db.ensure_schema(c)
    db.ensure_embedding_dim(c, dim=8)
    # clean slate
    c.execute(
        "TRUNCATE reports, runs, chunks, findings, judge_traces, "
        "assessor_corrections, llm_usage, run_completions, users, sessions "
        "RESTART IDENTITY CASCADE"
    )
    yield c
    c.close()


def test_ensure_schema_is_idempotent(conn):
    # Running twice must not error and must leave all core tables present.
    db.ensure_schema(conn)
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    ).fetchall()
    names = {r["table_name"] for r in rows}
    assert {
        "reports",
        "runs",
        "chunks",
        "findings",
        "judge_traces",
        "app_meta",
        "assessor_corrections",
        "llm_usage",
        "run_completions",
        "users",
        "sessions",
    } <= names


def test_schema_version_recorded(conn):
    row = conn.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()
    assert row["value"] == db.SCHEMA_VERSION


def test_chunks_has_vector_and_tsv_columns(conn):
    cols = {
        r["column_name"]: r["data_type"]
        for r in conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name='chunks'"
        ).fetchall()
    }
    assert "embedding" in cols  # pgvector type (USER-DEFINED)
    assert cols["text_tsv"] == "tsvector"


def test_is_active_is_boolean(conn):
    col = conn.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name='users' AND column_name='is_active'"
    ).fetchone()
    assert col["data_type"] == "boolean"
