from accordance.config import Settings, check_required_keys


def _settings(**kw) -> Settings:
    # Pass keys explicitly so a stray .env can't influence the result.
    base = dict(
        llm_model="fake:fake",
        embedding_model="fake:fake",
        llm_api_key="",
        openai_api_key="",
        voyage_api_key="",
    )
    base.update(kw)
    return Settings(**base)


def test_fully_fake_config_has_no_problems():
    assert check_required_keys(_settings()) == []


def test_real_llm_without_key_is_flagged():
    probs = check_required_keys(_settings(llm_model="openai:gpt-5-mini", llm_api_key=""))
    assert any("LLM_API_KEY" in p for p in probs)


def test_real_llm_with_key_is_ok():
    assert check_required_keys(
        _settings(llm_model="openai:gpt-5-mini", llm_api_key="sk-present")
    ) == []


def test_openai_embeddings_without_key_is_flagged():
    probs = check_required_keys(
        _settings(embedding_model="openai:text-embedding-3-small", openai_api_key="")
    )
    assert any("OPENAI_API_KEY" in p for p in probs)


def test_voyage_embeddings_without_key_is_flagged():
    probs = check_required_keys(
        _settings(embedding_model="voyage:voyage-3-lite", voyage_api_key="")
    )
    assert any("VOYAGE_API_KEY" in p for p in probs)


# ── embedding key may come from the gateway override ─────────────────


def test_embedding_api_key_satisfies_the_startup_check():
    """EMBEDDING_API_KEY alone must be enough.

    Routing embeddings through a gateway means OPENAI_API_KEY is legitimately
    unset — demanding it anyway hard-fails startup on a valid configuration.
    Validation must ask the same helper the runtime uses, or the two drift.
    """
    from accordance.config import Settings, check_required_keys

    s = Settings(
        database_url="postgresql://x/y",
        llm_model="fake:fake",
        embedding_model="openai:openai/text-embedding-3-small",
        openai_api_key="",
        embedding_api_key="sk-or-v1-test",
        embedding_base_url="https://openrouter.ai/api/v1",
    )
    assert not [p for p in check_required_keys(s) if "API_KEY" in p]


def test_missing_every_embedding_key_still_fails():
    from accordance.config import Settings, check_required_keys

    s = Settings(
        database_url="postgresql://x/y",
        llm_model="fake:fake",
        embedding_model="openai:text-embedding-3-small",
        openai_api_key="",
        embedding_api_key="",
    )
    assert any("EMBEDDING_API_KEY" in p or "OPENAI_API_KEY" in p for p in check_required_keys(s))
