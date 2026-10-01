"""The run detail exposes what the run cost.

Spend was only visible per-user in admin, so there was no way to see what a
single report cost — including after an inline retry, which books extra tokens
against the same run.
"""

from fastapi.testclient import TestClient

from accordance.auth.passwords import hash_password
from accordance.db import connection
from accordance.main import create_app


def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")


def _login(client):
    with connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            ("tester", hash_password("pw")),
        )
    client.post("/api/auth/login", json={"username": "tester", "password": "pw"})


def _seed(costs):
    with connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            ("tester", hash_password("pw")),
        )
        uid = conn.execute("SELECT id FROM users WHERE username='tester'").fetchone()["id"]
        conn.execute("INSERT INTO reports (id, name, created_by) VALUES ('rep','x.pdf',%s)", (uid,))
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status, created_by) "
            "VALUES ('run1','rep',1,'initial','x.pdf','sha','x.pdf','completed',%s)",
            (uid,),
        )
        for kind, c in costs:
            conn.execute(
                "INSERT INTO llm_usage (run_id, user_id, kind, model, input_tokens, "
                "output_tokens, cost_usd) VALUES ('run1',%s,%s,'m',1,1,%s)",
                (uid, kind, c),
            )


def test_run_detail_reports_total_cost(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")
    _seed([("judge", 0.0123), ("vision", 0.0045), ("embedding", 0.0002)])
    r = client.get("/api/runs/run1")
    assert r.status_code == 200
    assert round(r.json()["summary"]["cost_usd"], 6) == 0.017


def test_run_with_no_usage_reports_zero(monkeypatch, tmp_path):
    """A run that never called the LLM must report 0.0, not null — the badge
    should read $0.0000 rather than disappearing."""
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")
    _seed([])
    assert client.get("/api/runs/run1").json()["summary"]["cost_usd"] == 0.0
