from accordance.indexer.embedder import FakeEmbedder, build_embedder


def test_build_embedder_forwards_timeout_and_retries_to_openai():
    """A stalled embedding endpoint must not hang the indexing step unbounded —
    build_embedder must forward timeout + max_retries to the OpenAI client."""
    emb = build_embedder(
        "openai:text-embedding-3-small",
        api_key="sk-test",
        timeout=42.0,
        max_retries=4,
    )
    inner = emb._inner
    assert inner.request_timeout == 42.0
    assert inner.max_retries == 4


def test_build_embedder_fake_path_unaffected():
    emb = build_embedder("fake:fake", api_key="x", timeout=5.0, max_retries=1)
    assert isinstance(emb, FakeEmbedder)
    assert emb.dim == 8


def test_build_embedder_forwards_base_url():
    emb = build_embedder(
        "openai:openai/text-embedding-3-small",
        api_key="sk-test",
        base_url="https://openrouter.ai/api/v1",
    )
    assert str(emb._inner.openai_api_base).rstrip("/") == "https://openrouter.ai/api/v1"


def test_build_embedder_without_base_url_stays_direct():
    emb = build_embedder("openai:text-embedding-3-small", api_key="sk-test")
    base = emb._inner.openai_api_base
    assert base is None or "openrouter" not in str(base)


def test_build_embedder_openrouter_model_id_keeps_its_provider_prefix():
    """`openai:openai/text-embedding-3-small` must reach the API as
    `openai/text-embedding-3-small` — OpenRouter keys models by that full id,
    and only the leading `provider:` marker is ours to strip."""
    emb = build_embedder(
        "openai:openai/text-embedding-3-small",
        api_key="sk-test",
        base_url="https://openrouter.ai/api/v1",
    )
    assert emb._inner.model == "openai/text-embedding-3-small"
