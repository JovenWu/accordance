import json

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


def _seed(run_id, selected):
    with connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            ("tester", hash_password("pw")),
        )
        uid = conn.execute("SELECT id FROM users WHERE username='tester'").fetchone()["id"]
        conn.execute(
            "INSERT INTO reports (id, name, created_by) VALUES (%s, 'x.pdf', %s) ON CONFLICT DO NOTHING",
            ("rep", uid),
        )
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status, selected_disclosures, created_by) VALUES "
            "(%s, 'rep', 1, 'initial', 'x.pdf', 'sha', 'x.pdf', 'completed', %s, %s)",
            (run_id, json.dumps(selected) if selected else None, uid),
        )


def test_run_detail_reports_selected_total_for_subset(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    _seed("r1", ["2-1", "303-1"])
    client = TestClient(create_app())
    _login(client)
    r = client.get("/api/runs/r1")
    assert r.status_code == 200
    assert r.json()["summary"]["selected_total"] == 2


def test_run_detail_selected_total_none_when_all(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    _seed("r2", None)
    client = TestClient(create_app())
    _login(client)
    r = client.get("/api/runs/r2")
    assert r.status_code == 200
    assert r.json()["summary"]["selected_total"] is None
