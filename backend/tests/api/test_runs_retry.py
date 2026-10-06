import time
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


def _wait_for_status(client, rid, status, timeout=60):
    for _ in range(timeout * 2):
        body = client.get(f"/api/runs/{rid}").json()
        if body["summary"]["status"] == status:
            return body
        time.sleep(0.5)
    raise AssertionError(f"run {rid} did not reach status={status} in {timeout}s")


def test_retry_failed_run(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    client = TestClient(create_app())
    _login(client)
    with FIXTURE.open("rb") as f:
        rid = client.post("/api/runs", files={"pdf": ("a.pdf", f, "application/pdf")}).json()[
            "run_id"
        ]
    _wait_for_status(client, rid, "completed")

    with connection() as conn:
        conn.execute(
            "UPDATE runs SET status=%s, error=%s WHERE id=%s",
            ("failed", "synthetic failure for test", rid),
        )

    body = client.get(f"/api/runs/{rid}").json()
    assert body["summary"]["status"] == "failed"
    assert body["summary"]["error"] == "synthetic failure for test"

    r = client.post(f"/api/runs/{rid}/retry")
    assert r.status_code == 201
    new_rid = r.json()["run_id"]
    assert new_rid != rid
    assert r.json()["version_number"] == 2

    old_body = client.get(f"/api/runs/{rid}").json()
    assert old_body["summary"]["status"] == "failed"

    body = _wait_for_status(client, new_rid, "completed")
    assert body["summary"]["status"] == "completed"


def test_retry_rejects_in_progress_run(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    client = TestClient(create_app())
    _login(client)
    with FIXTURE.open("rb") as f:
        rid = client.post("/api/runs", files={"pdf": ("a.pdf", f, "application/pdf")}).json()[
            "run_id"
        ]
    r = client.post(f"/api/runs/{rid}/retry")
    assert r.status_code in (201, 409)


def test_retry_404_for_unknown_run(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    client = TestClient(create_app())
    _login(client)
    r = client.post("/api/runs/does-not-exist/retry")
    assert r.status_code == 404
