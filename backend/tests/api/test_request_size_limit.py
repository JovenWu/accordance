"""The ASGI body-size middleware rejects oversized requests at the door (413)."""

from fastapi.testclient import TestClient

from accordance.main import create_app


def _client(monkeypatch, tmp_path, max_request_mb="1"):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("MAX_REQUEST_MB", max_request_mb)
    return TestClient(create_app())


def test_oversized_body_rejected_with_413(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path, max_request_mb="1")
    # 2 MB body, cap is 1 MB -> refused before routing/auth even runs.
    r = client.post("/api/runs", content=b"x" * (2 * 1024 * 1024))
    assert r.status_code == 413


def test_small_request_passes_middleware(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path, max_request_mb="1")
    # Under the cap: the middleware lets it through (health needs no auth).
    r = client.get("/api/health")
    assert r.status_code in (200, 503)  # reachable, not blocked by the size guard
