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


def _fake_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")


def _upload(client) -> str:
    with FIXTURE.open("rb") as f:
        r = client.post("/api/runs", files={"pdf": ("sample.pdf", f, "application/pdf")})
    assert r.status_code == 201, r.text
    return r.json()["run_id"]


def test_get_run_pdf_returns_pdf_bytes(tmp_path, monkeypatch):
    _fake_env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    run_id = _upload(client)

    r = client.get(f"/api/runs/{run_id}/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content[:5] == b"%PDF-"


def test_get_run_pdf_unknown_run_404(tmp_path, monkeypatch):
    _fake_env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)

    r = client.get("/api/runs/does-not-exist/pdf")
    assert r.status_code == 404


def test_get_run_pdf_missing_file_404(tmp_path, monkeypatch):
    _fake_env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    run_id = _upload(client)

    # Remove the stored PDF from disk, leaving the DB row intact.
    next(tmp_path.rglob(f"{run_id}.pdf")).unlink()

    r = client.get(f"/api/runs/{run_id}/pdf")
    assert r.status_code == 404
