import pytest

from accordance import db
from accordance.config import get_settings


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


def _seed_run(conn, run_id: str, status: str) -> None:
    """Insert the minimal rows needed to create a run with the given status."""
    conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (%s, %s) "
        "ON CONFLICT (username) DO NOTHING",
        ("u", "x"),
    )
    conn.execute(
        "INSERT INTO reports (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
        ("rep1", "r"),
    )
    row = conn.execute("SELECT COUNT(*) AS n FROM runs WHERE report_id='rep1'").fetchone()
    version = (row["n"] or 0) + 1
    conn.execute(
        "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
        "pdf_sha256, pdf_path, status) VALUES "
        "(%s, %s, %s, 'initial', 'f.pdf', 'sha', 'p', %s)",
        (run_id, "rep1", version, status),
    )


def test_reconcile_marks_all_inflight_statuses_failed(conn):
    """All four in-flight statuses must be marked failed; count must match."""
    inflight = ["queued", "extracting", "indexing", "judging"]
    for i, status in enumerate(inflight):
        _seed_run(conn, f"run-{i}", status)

    from accordance.db import reconcile_orphaned_runs

    n = reconcile_orphaned_runs(conn)
    assert n == len(inflight), f"Expected {len(inflight)} updated rows, got {n}"

    rows = conn.execute("SELECT id, status FROM runs ORDER BY id").fetchall()
    for row in rows:
        assert row["status"] == "failed", (
            f"run {row['id']} has status {row['status']!r}, expected 'failed'"
        )


def test_reconcile_leaves_terminal_statuses_untouched(conn):
    """Runs already in terminal state (completed/failed) must NOT be mutated."""
    terminal_statuses = ["completed", "failed"]
    for i, status in enumerate(terminal_statuses):
        _seed_run(conn, f"run-t{i}", status)

    from accordance.db import reconcile_orphaned_runs

    n = reconcile_orphaned_runs(conn)
    assert n == 0, f"Expected 0 updated rows for terminal statuses, got {n}"

    rows = {r["id"]: r["status"] for r in conn.execute("SELECT id, status FROM runs").fetchall()}
    assert rows["run-t0"] == "completed"
    assert rows["run-t1"] == "failed"


def test_reconcile_idempotent(conn):
    """A second call after reconciliation must return 0 (nothing left to fix)."""
    _seed_run(conn, "run-idem", "judging")

    from accordance.db import reconcile_orphaned_runs

    first = reconcile_orphaned_runs(conn)
    assert first == 1

    second = reconcile_orphaned_runs(conn)
    assert second == 0, "Second reconcile call should find nothing in-flight"


def test_reconcile_marks_inflight_failed(conn):
    """Original single-case regression guard: judging → failed."""
    conn.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", ("u", "x"))
    conn.execute("INSERT INTO reports (id, name) VALUES (%s, %s)", ("rep1", "r"))
    conn.execute(
        "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
        "pdf_sha256, pdf_path, status) VALUES "
        "(%s, %s, 1, 'initial', 'f.pdf', 'sha', 'p', 'judging')",
        ("run1", "rep1"),
    )
    from accordance.db import reconcile_orphaned_runs

    n = reconcile_orphaned_runs(conn)
    assert n == 1
    assert conn.execute("SELECT status FROM runs WHERE id='run1'").fetchone()["status"] == "failed"
