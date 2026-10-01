from fastapi.testclient import TestClient

from accordance.main import create_app


def test_health(tmp_path, monkeypatch):
    # Isolate DATA_DIR to tmp_path: the deep healthcheck opens a DB connection,
    # which must never touch the real ./data (corrupts a live Docker bind-mount).
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
