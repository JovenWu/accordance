from pathlib import Path

from accordance.config import Settings


def test_settings_load_with_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MODEL", "anthropic:claude-sonnet-4-5")
    monkeypatch.setenv("EMBEDDING_MODEL", "openai:text-embedding-3-small")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    s = Settings()

    assert s.llm_model == "anthropic:claude-sonnet-4-5"
    assert s.embedding_model == "openai:text-embedding-3-small"
    assert s.data_dir == Path(tmp_path)
    assert s.judge_concurrency == 3
    assert s.vision_fallback_enabled is True


def test_llm_timeout_default(tmp_path, monkeypatch):
    """llm_timeout defaults to 60.0 seconds."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = Settings()
    assert s.llm_timeout == 60.0


def test_llm_reasoning_effort_defaults_to_unset(tmp_path, monkeypatch):
    """Blank by default so the parameter is never sent unless asked for.

    Reasoning tokens bill as output, so this is a cost lever — but non-
    reasoning models and some OpenAI-compatible proxies 400 on the parameter,
    so shipping any concrete default would break existing deployments.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert Settings().llm_reasoning_effort == ""


def test_llm_reasoning_effort_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_REASONING_EFFORT", "medium")
    assert Settings().llm_reasoning_effort == "medium"


def test_llm_max_retries_default(tmp_path, monkeypatch):
    """llm_max_retries defaults to 2 (bounded, down from old hardcoded 5)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = Settings()
    assert s.llm_max_retries == 2


def test_llm_timeout_overridable(tmp_path, monkeypatch):
    """LLM_TIMEOUT env var overrides the default."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_TIMEOUT", "30")
    s = Settings()
    assert s.llm_timeout == 30.0


def test_llm_max_retries_overridable(tmp_path, monkeypatch):
    """LLM_MAX_RETRIES env var overrides the default."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")
    s = Settings()
    assert s.llm_max_retries == 0


def test_embedding_credentials_default_to_the_provider_key(tmp_path, monkeypatch):
    """Production sets neither override — behaviour must be unchanged."""
    from accordance.config import embedding_credentials

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = Settings(embedding_model="openai:text-embedding-3-small", openai_api_key="sk-real")
    assert embedding_credentials(s) == ("sk-real", "")


def test_embedding_api_key_overrides_the_provider_key(tmp_path, monkeypatch):
    """Without this, pointing EMBEDDING_BASE_URL at a third-party gateway would
    send OPENAI_API_KEY to that gateway."""
    from accordance.config import embedding_credentials

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = Settings(
        embedding_model="openai:openai/text-embedding-3-small",
        openai_api_key="sk-real",
        embedding_api_key="sk-or-v1-test",
        embedding_base_url="https://openrouter.ai/api/v1",
    )
    assert embedding_credentials(s) == ("sk-or-v1-test", "https://openrouter.ai/api/v1")


def test_embedding_credentials_falls_back_to_voyage(tmp_path, monkeypatch):
    from accordance.config import embedding_credentials

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = Settings(embedding_model="voyage:voyage-3-lite", voyage_api_key="pa-key")
    assert embedding_credentials(s)[0] == "pa-key"


def test_embedding_base_url_defaults_blank(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert Settings().embedding_base_url == ""
    assert Settings().embedding_api_key == ""


def test_llm_service_tier_defaults_to_unset(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert Settings().llm_service_tier == ""


def test_llm_service_tier_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_SERVICE_TIER", "flex")
    assert Settings().llm_service_tier == "flex"


def test_pool_size_adds_rather_than_multiplies_concurrency(tmp_path, monkeypatch):
    """Workers wait for the LLM slot before borrowing a connection, so peak
    demand is (spines) + (globally-capped workers), not runs x workers.

    Under the old multiplying formula, 10 runs x 12 needed 138 connections —
    beyond Postgres' default max_connections of 100 — to perform exactly
    judge_concurrency calls' worth of work.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = Settings(max_concurrent_runs=10, judge_concurrency=12, db_pool_max_size=0)
    assert s.effective_pool_max_size == 10 + 12 + 8


def test_explicit_pool_size_still_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = Settings(max_concurrent_runs=10, judge_concurrency=12, db_pool_max_size=64)
    assert s.effective_pool_max_size == 64
