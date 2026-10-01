"""aggregate_node must not overwrite a 'cancelled' status written by stop_run
in the race window between its is_cancelled() check and its completed UPDATE."""

from accordance import db
from accordance.api import events as events_mod
from accordance.api.cancellation import registry as cancel_registry
from accordance.graph.nodes import aggregate_node


def _seed_run(conn, run_id, status):
    conn.execute("INSERT INTO reports (id, name) VALUES ('rep1', 'r.pdf')")
    conn.execute(
        "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
        "pdf_sha256, pdf_path, status) "
        "VALUES (%s, 'rep1', 1, 'initial', 'r.pdf', %s, '/tmp/r.pdf', %s)",
        (run_id, run_id, status),
    )


def test_aggregate_does_not_overwrite_cancelled_status(monkeypatch):
    with db.connection() as conn:
        run_id = "race-1"
        # stop_run already flipped the DB to 'cancelled' ...
        _seed_run(conn, run_id, "cancelled")
        # ... but the in-memory cancel flag isn't set yet (the race window that lets
        # aggregate_node fall through to its 'completed' branch).
        cancel_registry.clear(run_id)

        published = []
        monkeypatch.setattr(events_mod.bus, "publish", lambda rid, ev: published.append((rid, ev)))

        aggregate_node({"run_id": run_id}, conn)

        status = conn.execute("SELECT status FROM runs WHERE id=%s", (run_id,)).fetchone()["status"]
        assert status == "cancelled"  # NOT silently flipped to 'completed'
        assert all(ev.get("type") != "completed" for _, ev in published)


def test_aggregate_completes_a_normal_run(monkeypatch):
    with db.connection() as conn:
        run_id = "ok-1"
        _seed_run(conn, run_id, "judging")
        cancel_registry.clear(run_id)

        published = []
        monkeypatch.setattr(events_mod.bus, "publish", lambda rid, ev: published.append((rid, ev)))

        aggregate_node({"run_id": run_id}, conn)

        status = conn.execute("SELECT status FROM runs WHERE id=%s", (run_id,)).fetchone()["status"]
        assert status == "completed"
        assert any(ev.get("type") == "completed" for _, ev in published)
