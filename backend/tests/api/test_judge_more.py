from pathlib import Path

from fastapi.testclient import TestClient

from accordance.auth.passwords import hash_password
from accordance.db import connection
from accordance.main import create_app


def _login(client):
    with connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            ("tester", hash_password("pw")),
        )
    client.post("/api/auth/login", json={"username": "tester", "password": "pw"})


FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_report.pdf"


def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")


def _seed_run(status, judged_ids, finding_status="covered"):
    """Insert a report + run + findings directly (no async graph)."""
    with connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            ("tester", hash_password("pw")),
        )
        uid = conn.execute("SELECT id FROM users WHERE username='tester'").fetchone()["id"]
        conn.execute(
            "INSERT INTO reports (id, name, created_by) VALUES (%s, %s, %s)",
            ("rep", "x.pdf", uid),
        )
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status, selected_disclosures, created_by) VALUES "
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            ("run1", "rep", 1, "initial", "x.pdf", "sha", "x.pdf", status, '["2-1"]', uid),
        )
        for did in judged_ids:
            conn.execute(
                "INSERT INTO findings (run_id, disclosure_id, standard, status, note, "
                "elements_json, suggested_fix) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                ("run1", did, "GRI 2", finding_status, "n", "[]", "f"),
            )


def test_judge_more_on_running_run_is_409(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")  # ensures schema exists
    _seed_run(status="judging", judged_ids=["2-1"])
    r = client.post("/api/runs/run1/judge-more", json={"disclosure_ids": ["2-2"]})
    assert r.status_code == 409


def test_judge_more_empty_is_400(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")
    _seed_run(status="completed", judged_ids=["2-1"])
    r = client.post("/api/runs/run1/judge-more", json={"disclosure_ids": []})
    assert r.status_code == 400


def test_judge_more_unknown_id_is_400(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")
    _seed_run(status="completed", judged_ids=["2-1"])
    r = client.post("/api/runs/run1/judge-more", json={"disclosure_ids": ["nope"]})
    assert r.status_code == 400


def test_judge_more_all_already_judged_is_noop(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")
    _seed_run(status="completed", judged_ids=["2-1"])
    r = client.post("/api/runs/run1/judge-more", json={"disclosure_ids": ["2-1"]})
    assert r.status_code == 200
    assert r.json()["judged"] == []


# ── retrying a failed disclosure ─────────────────────────────────────
# An errored disclosure HAS a finding, so the additive filter skipped it and
# there was no way to repair one without spawning a whole new run version.
# Re-judging must happen on the SAME run so the finding is fixed in place and
# the retry's spend lands against that run.


def test_judge_more_rejudges_a_failed_disclosure(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")
    _seed_run(status="completed", judged_ids=["2-1"], finding_status="error")
    r = client.post("/api/runs/run1/judge-more", json={"disclosure_ids": ["2-1"]})
    assert r.status_code == 200
    assert r.json()["judged"] == ["2-1"], "an errored disclosure must be eligible for re-judging"
    assert r.json()["run_id"] == "run1", "the repair must target the SAME run, not a new version"


def test_judge_more_still_skips_a_successful_disclosure(monkeypatch, tmp_path):
    """Only failures are retryable. Silently re-judging good findings would
    cost money and churn verdicts against a 13%/24% run-to-run noise floor."""
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")
    _seed_run(status="completed", judged_ids=["2-1"], finding_status="partial")
    r = client.post("/api/runs/run1/judge-more", json={"disclosure_ids": ["2-1"]})
    assert r.json()["judged"] == []


def test_judge_more_claims_the_run_atomically(monkeypatch, tmp_path):
    """Two concurrent judge-more requests must not both start a graph.

    The terminal-status check is a read, so without a conditional UPDATE both
    callers see 'completed' and two thread pools write the same findings. The
    per-row Retry button turned rapid double-fire from deliberate into ordinary.
    """
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")
    _seed_run(status="completed", judged_ids=["2-1"], finding_status="error")

    claim = (
        "UPDATE runs SET status='judging', completed_at=NULL "
        "WHERE id=%s AND status IN ('completed','failed','cancelled')"
    )
    with connection() as conn:
        assert conn.execute(claim, ("run1",)).rowcount == 1, "first claim must win"
        assert conn.execute(claim, ("run1",)).rowcount == 0, "second claim must lose"

    # And the endpoint surfaces that loss as a 409 rather than double-running.
    r = client.post("/api/runs/run1/judge-more", json={"disclosure_ids": ["2-1"]})
    assert r.status_code == 409
