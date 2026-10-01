from pathlib import Path

from fastapi.testclient import TestClient

from accordance.auth.passwords import hash_password
from accordance.config import get_settings
from accordance.db import connection as db_conn
from accordance.main import create_app


def _login(client):
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES ('tester', %s) "
            "ON CONFLICT (username) DO NOTHING",
            (hash_password("pw"),),
        )
    client.post("/api/auth/login", json={"username": "tester", "password": "pw"})


FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_report.pdf"


def test_stream_yields_completed_eventually(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    get_settings.cache_clear()

    client = TestClient(create_app())
    _login(client)
    with FIXTURE.open("rb") as f:
        run_id = client.post(
            "/api/runs", files={"pdf": ("sample.pdf", f, "application/pdf")}
        ).json()["run_id"]

    saw_completed = False
    with client.stream("GET", f"/api/runs/{run_id}/stream") as r:
        for line in r.iter_lines():
            if "completed" in line:
                saw_completed = True
                break
    assert saw_completed
