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


def test_get_run_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    client = TestClient(create_app())
    _login(client)
    with FIXTURE.open("rb") as f:
        upload = client.post("/api/runs", files={"pdf": ("sample.pdf", f, "application/pdf")})
    run_id = upload.json()["run_id"]

    detail = client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["summary"]["id"] == run_id
    assert isinstance(body["findings"], list)
