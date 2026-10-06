"""One source of truth for embedding dimension, keyed by the full model id so a
non-1536 model (e.g. text-embedding-3-large = 3072) is sized correctly for vec0."""
import pytest

from accordance.indexer.embedder import build_embedder, embedding_dim


def test_embedding_dim_known_models():
    assert embedding_dim("openai:text-embedding-3-small") == 1536
    assert embedding_dim("openai:text-embedding-3-large") == 3072
    assert embedding_dim("voyage:voyage-3-lite") == 512
    assert embedding_dim("fake:fake") == 8


def test_embedding_dim_unknown_provider_raises():
    with pytest.raises(ValueError):
        embedding_dim("cohere:embed-english-v3")


def test_build_embedder_large_model_reports_3072():
    emb = build_embedder("openai:text-embedding-3-large", api_key="x")
    assert emb.dim == 3072
