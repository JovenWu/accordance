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


def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")


def _seed_completed_run(selected):
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
            "(%s, %s, 1, 'initial', 'x.pdf', 'sha', 'x.pdf', 'completed', %s, %s)",
            ("src", "rep", json.dumps(selected) if selected else None, uid),
        )


def _stored(run_id):
    with connection() as conn:
        row = conn.execute(
            "SELECT selected_disclosures FROM runs WHERE id=%s", (run_id,)
        ).fetchone()
    return row["selected_disclosures"] if row else None


def test_retry_with_subset_overrides_selection(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _seed_completed_run(["2-1", "303-1"])
    client = TestClient(create_app())
    _login(client)
    r = client.post("/api/runs/src/retry", json={"disclosure_ids": ["2-2"]})
    assert r.status_code == 201
    assert json.loads(_stored(r.json()["run_id"])) == ["2-2"]


def test_retry_without_body_inherits(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _seed_completed_run(["2-1", "303-1"])
    client = TestClient(create_app())
    _login(client)
    r = client.post("/api/runs/src/retry")
    assert r.status_code == 201
    assert set(json.loads(_stored(r.json()["run_id"]))) == {"2-1", "303-1"}


def test_retry_empty_selection_is_400(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _seed_completed_run(["2-1"])
    client = TestClient(create_app())
    _login(client)
    r = client.post("/api/runs/src/retry", json={"disclosure_ids": []})
    assert r.status_code == 400


def test_retry_unknown_id_is_400(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _seed_completed_run(["2-1"])
    client = TestClient(create_app())
    _login(client)
    r = client.post("/api/runs/src/retry", json={"disclosure_ids": ["nope"]})
    assert r.status_code == 400
