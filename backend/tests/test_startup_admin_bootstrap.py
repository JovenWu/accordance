from fastapi.testclient import TestClient

from accordance.db import connection
from accordance.main import create_app


def test_startup_bootstraps_admin(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("ADMIN_USERNAME", "root")
    monkeypatch.setenv("ADMIN_PASSWORD", "supersecret")

    with TestClient(create_app()) as client:
        assert client.get("/api/health").status_code == 200
        r = client.post(
            "/api/auth/login", json={"username": "root", "password": "supersecret"}
        )
        assert r.status_code == 200

        with connection() as conn:
            row = conn.execute(
                "SELECT is_admin, is_active FROM users WHERE username='root'"
            ).fetchone()

    assert row is not None and row["is_admin"] is True and row["is_active"] is True
