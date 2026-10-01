import json
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


def _selected(run_id):
    with connection() as conn:
        row = conn.execute(
            "SELECT selected_disclosures FROM runs WHERE id=%s", (run_id,)
        ).fetchone()
    return row["selected_disclosures"] if row else None


def test_upload_with_subset_stores_selection(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    with FIXTURE.open("rb") as f:
        r = client.post(
            "/api/runs",
            files={"pdf": ("a.pdf", f, "application/pdf")},
            data={"disclosure_ids": '["2-1", "303-1"]'},
        )
    assert r.status_code == 201
    stored = _selected(r.json()["run_id"])
    assert stored is not None
    assert set(json.loads(stored)) == {"2-1", "303-1"}


def test_upload_without_selection_stores_null(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    with FIXTURE.open("rb") as f:
        r = client.post("/api/runs", files={"pdf": ("b.pdf", f, "application/pdf")})
    assert r.status_code == 201
    assert _selected(r.json()["run_id"]) is None


def test_upload_empty_selection_is_400(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    with FIXTURE.open("rb") as f:
        r = client.post(
            "/api/runs",
            files={"pdf": ("c.pdf", f, "application/pdf")},
            data={"disclosure_ids": "[]"},
        )
    assert r.status_code == 400


def test_upload_unknown_id_is_400(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    with FIXTURE.open("rb") as f:
        r = client.post(
            "/api/runs",
            files={"pdf": ("d.pdf", f, "application/pdf")},
            data={"disclosure_ids": '["not-real"]'},
        )
    assert r.status_code == 400
