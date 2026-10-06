"""aggregate_node must not mark a run 'completed' while silently hiding a
disclosure whose finding-write failed. It reconciles the expected disclosure
set against the persisted findings and records an explicit 'error' finding for
any that are missing.
"""

from types import SimpleNamespace

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


def _seed_finding(conn, run_id, did, standard, status):
    conn.execute(
        "INSERT INTO findings (run_id, disclosure_id, standard, status, note, "
        "elements_json, suggested_fix) VALUES (%s, %s, %s, %s, 'ok', '[]', '')",
        (run_id, did, standard, status),
    )


def _disc(did, standard):
    return SimpleNamespace(id=did, standard=standard)


def test_missing_finding_recorded_as_error(monkeypatch):
    with db.connection() as conn:
        run_id = "recon-1"
        _seed_run(conn, run_id, "judging")
        cancel_registry.clear(run_id)
        _seed_finding(conn, run_id, "2-1", "GRI 2", "covered")
        monkeypatch.setattr(events_mod.bus, "publish", lambda rid, ev: None)

        expected = [_disc("2-1", "GRI 2"), _disc("305-1", "GRI 305")]
        aggregate_node({"run_id": run_id}, conn, expected_disclosures=expected)

        status = conn.execute("SELECT status FROM runs WHERE id=%s", (run_id,)).fetchone()["status"]
        assert status == "completed"

        row = conn.execute(
            "SELECT status FROM findings WHERE run_id=%s AND disclosure_id='305-1'",
            (run_id,),
        ).fetchone()
        assert row is not None
        assert row["status"] == "error"

        kept = conn.execute(
            "SELECT status FROM findings WHERE run_id=%s AND disclosure_id='2-1'",
            (run_id,),
        ).fetchone()["status"]
        assert kept == "covered"


def test_no_missing_findings_inserts_nothing(monkeypatch):
    with db.connection() as conn:
        run_id = "recon-2"
        _seed_run(conn, run_id, "judging")
        cancel_registry.clear(run_id)
        _seed_finding(conn, run_id, "2-1", "GRI 2", "covered")
        _seed_finding(conn, run_id, "305-1", "GRI 305", "partial")
        monkeypatch.setattr(events_mod.bus, "publish", lambda rid, ev: None)

        expected = [_disc("2-1", "GRI 2"), _disc("305-1", "GRI 305")]
        aggregate_node({"run_id": run_id}, conn, expected_disclosures=expected)

        n = conn.execute(
            "SELECT COUNT(*) AS n FROM findings WHERE run_id=%s", (run_id,)
        ).fetchone()["n"]
        assert n == 2
        errored = conn.execute(
            "SELECT COUNT(*) AS n FROM findings WHERE run_id=%s AND status='error'",
            (run_id,),
        ).fetchone()["n"]
        assert errored == 0


def test_cancelled_run_skips_reconciliation(monkeypatch):
    with db.connection() as conn:
        run_id = "recon-3"
        _seed_run(conn, run_id, "cancelled")
        cancel_registry.clear(run_id)
        monkeypatch.setattr(events_mod.bus, "publish", lambda rid, ev: None)

        expected = [_disc("305-1", "GRI 305")]
        aggregate_node({"run_id": run_id}, conn, expected_disclosures=expected)

        n = conn.execute(
            "SELECT COUNT(*) AS n FROM findings WHERE run_id=%s", (run_id,)
        ).fetchone()["n"]
        assert n == 0
