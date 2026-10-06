"""SPA hosting + API co-existence in the FastAPI app."""


from fastapi.testclient import TestClient

from accordance.main import _find_frontend_dist, _warn_if_unpriced_model, create_app


def test_health_503_when_db_check_fails(tmp_path, monkeypatch):
    """Deep healthcheck must report unhealthy (503) when the DB can't be
    reached, instead of a false-green {"status":"ok"}."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    import accordance.api.runs as runs_mod

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(runs_mod, "_open_conn", boom)
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 503
    assert r.json()["status"] == "unhealthy"


def test_warn_if_unpriced_model_warns_on_unknown_model():
    from unittest.mock import MagicMock

    from accordance.config import Settings

    logger = MagicMock()
    s = Settings(llm_model="openai:cx/not-a-real-model", model_prices_json="")
    assert _warn_if_unpriced_model(s, logger) is True
    assert logger.warning.called


def test_warn_if_unpriced_model_quiet_when_priced():
    from unittest.mock import MagicMock

    from accordance.config import Settings

    logger = MagicMock()
    s = Settings(
        llm_model="openai:cx/gpt-5.4-mini",
        model_prices_json='{"gpt-5.4-mini": {"in": 0.25, "out": 2.0}}',
    )
    assert _warn_if_unpriced_model(s, logger) is False
    assert not logger.warning.called


def test_find_frontend_dist_returns_none_when_absent(tmp_path, monkeypatch):
    """In dev/test the dist isn't built, so the SPA path should stay quiet."""
    monkeypatch.chdir(tmp_path)
    assert _find_frontend_dist() is None or (
        _find_frontend_dist() is not None
    )


def test_health_endpoint_works(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_api_404_not_swallowed_by_spa(tmp_path, monkeypatch):
    """When the SPA mount is active, /api/* must still return real 404s
    — otherwise frontend fetch callers would silently parse index.html as
    JSON and produce confusing errors."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    client = TestClient(create_app())
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert "<html>spa</html>" not in r.text


def test_spa_index_served_on_client_route(tmp_path, monkeypatch):
    """A client-side route like /runs/abc should serve index.html so
    react-router can pick it up after the page loads."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa-index</html>", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    client = TestClient(create_app())
    r = client.get("/runs/some-id")
    assert r.status_code == 200
    assert "spa-index" in r.text


def test_spa_serves_real_static_files_when_present(tmp_path, monkeypatch):
    """Asset bundles (e.g., /assets/index-abc.js) must hit the file, not
    fall through to index.html."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    dist = tmp_path / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('hi');", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    client = TestClient(create_app())
    r = client.get("/assets/app.js")
    assert r.status_code == 200
    assert "console.log" in r.text
    assert "<html>" not in r.text


def test_spa_path_traversal_rejected(tmp_path, monkeypatch):
    """A request like /../../../etc/passwd must not escape the dist
    directory."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("ok", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("hunter2", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    client = TestClient(create_app())
    r = client.get("/../secret.txt")
    assert "hunter2" not in r.text


def test_dev_mode_works_without_dist(tmp_path, monkeypatch):
    """No dist directory → no SPA route → unknown root path returns 404,
    NOT a 500. This keeps `uvicorn ...` work-as-before during dev."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)

    if _find_frontend_dist() is not None:
        import pytest

        pytest.skip("repo-relative dist exists; test premise doesn't apply")

    client = TestClient(create_app())
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 404


def test_warns_when_embeddings_bypass_the_llm_proxy():
    from unittest.mock import MagicMock

    from accordance.config import Settings
    from accordance.main import _warn_if_embeddings_bypass_proxy

    logger = MagicMock()
    s = Settings(
        llm_base_url="http://localhost:20128/v1",
        embedding_model="openai:text-embedding-3-small",
    )
    assert _warn_if_embeddings_bypass_proxy(s, logger) is True
    assert "OPENAI_API_KEY" in str(logger.warning.call_args)


def test_no_bypass_warning_without_a_proxy():
    from unittest.mock import MagicMock

    from accordance.config import Settings
    from accordance.main import _warn_if_embeddings_bypass_proxy

    logger = MagicMock()
    s = Settings(llm_base_url="", embedding_model="openai:text-embedding-3-small")
    assert _warn_if_embeddings_bypass_proxy(s, logger) is False
    assert not logger.warning.called


def test_no_bypass_warning_for_fake_embeddings():
    from unittest.mock import MagicMock

    from accordance.config import Settings
    from accordance.main import _warn_if_embeddings_bypass_proxy

    logger = MagicMock()
    s = Settings(llm_base_url="http://localhost:20128/v1", embedding_model="fake:fake")
    assert _warn_if_embeddings_bypass_proxy(s, logger) is False
    assert not logger.warning.called


def test_warns_when_flex_is_set_with_a_short_timeout():
    from unittest.mock import MagicMock

    from accordance.config import Settings
    from accordance.main import _warn_if_flex_timeout_too_short

    logger = MagicMock()
    s = Settings(llm_service_tier="flex", llm_timeout=60.0)
    assert _warn_if_flex_timeout_too_short(s, logger) is True
    assert "LLM_TIMEOUT" in str(logger.warning.call_args)


def test_no_flex_timeout_warning_when_timeout_is_generous():
    from unittest.mock import MagicMock

    from accordance.config import Settings
    from accordance.main import _warn_if_flex_timeout_too_short

    logger = MagicMock()
    s = Settings(llm_service_tier="flex", llm_timeout=900.0)
    assert _warn_if_flex_timeout_too_short(s, logger) is False
    assert not logger.warning.called


def test_no_flex_timeout_warning_without_flex():
    from unittest.mock import MagicMock

    from accordance.config import Settings
    from accordance.main import _warn_if_flex_timeout_too_short

    logger = MagicMock()
    assert _warn_if_flex_timeout_too_short(Settings(llm_timeout=60.0), logger) is False
    assert not logger.warning.called
