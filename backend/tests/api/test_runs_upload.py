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


def test_upload_creates_run(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    app = create_app()
    client = TestClient(app)
    _login(client)
    with FIXTURE.open("rb") as f:
        r = client.post("/api/runs", files={"pdf": ("sample.pdf", f, "application/pdf")})
    assert r.status_code == 201
    body = r.json()
    assert "run_id" in body
    assert "report_id" in body
    assert body["version_number"] == 1

    with FIXTURE.open("rb") as f:
        r2 = client.post("/api/runs", files={"pdf": ("sample.pdf", f, "application/pdf")})
    assert r2.json()["run_id"] == body["run_id"]


def test_dedup_returns_existing_report(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    client = TestClient(create_app())
    _login(client)
    with FIXTURE.open("rb") as f:
        body = f.read()
    r1 = client.post("/api/runs", files={"pdf": ("a.pdf", body, "application/pdf")})
    assert r1.status_code == 201
    j1 = r1.json()
    assert {"report_id", "run_id"}.issubset(j1.keys())
    assert j1["version_number"] == 1

    r2 = client.post("/api/runs", files={"pdf": ("a.pdf", body, "application/pdf")})
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["deduplicated"] is True
    assert j2["report_id"] == j1["report_id"]
    assert j2["run_id"] == j1["run_id"]
