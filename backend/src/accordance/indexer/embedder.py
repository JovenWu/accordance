import hashlib
from typing import Protocol

_EMBEDDING_DIMS: dict[str, int] = {
    "openai:text-embedding-3-small": 1536,
    "openai:text-embedding-3-large": 3072,
    "openai:text-embedding-ada-002": 1536,
    "voyage:voyage-3-lite": 512,
    "voyage:voyage-3": 1024,
}
_PROVIDER_DEFAULT_DIM: dict[str, int] = {"openai": 1536, "voyage": 512}


def embedding_dim(model: str) -> int:
    """Vector dimension for a `provider:model` embedding id.

    Exact match wins; otherwise falls back to the provider default. `fake:*`
    is always 8 (FakeEmbedder). Raises ValueError for unknown providers so a
    misconfiguration fails fast at startup instead of producing mismatched
    vector inserts on every run.
    """
    if model.startswith("fake:"):
        return 8
    if model in _EMBEDDING_DIMS:
        return _EMBEDDING_DIMS[model]
    provider = model.split(":", 1)[0]
    if provider in _PROVIDER_DEFAULT_DIM:
        return _PROVIDER_DEFAULT_DIM[provider]
    raise ValueError(f"Unknown embedding model (cannot determine dimension): {model!r}")


class Embedder(Protocol):
    def embed_query(self, text: str) -> list[float]: ...
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def dim(self) -> int: ...


class FakeEmbedder:
    """Deterministic hash-based pseudo-embedder for tests. Not for production."""

    def __init__(self, dim: int = 8) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def _hash_to_vec(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        return [(b / 127.5) - 1.0 for b in h[: self._dim]]

    def embed_query(self, text: str) -> list[float]:
        return self._hash_to_vec(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_to_vec(t) for t in texts]


class LangChainEmbedder:
    """Thin wrapper around a LangChain embeddings object so we can mock the protocol."""

    def __init__(self, lc_embeddings, dim: int) -> None:
        self._inner = lc_embeddings
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def embed_query(self, text: str) -> list[float]:
        return self._inner.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._inner.embed_documents(texts)


def build_embedder(
    model: str,
    api_key: str,
    *,
    timeout: float | None = None,
    max_retries: int | None = None,
    base_url: str = "",
) -> Embedder:
    """Build an embedder from a `provider:model` string.

    Supports: openai:text-embedding-3-small (dim=1536), voyage:voyage-3-lite (dim=512),
    fake:fake (FakeEmbedder, for tests).

    ``timeout``/``max_retries`` bound the embedding API call so a stalled or
    throttling endpoint can't hang the indexing step (and its DB connection)
    unbounded — mirroring the judge LLM's timeout/retry handling.

    ``base_url`` routes embeddings through an OpenAI-compatible gateway
    (OpenRouter, LiteLLM, Azure, ...). It is SEPARATE from the judge's
    LLM_BASE_URL on purpose: the two legs can live on different accounts, and
    conflating them hid a dead embedding key behind "judge failed" errors.
    Blank keeps the historical behaviour — straight to the provider — so any
    deployment that doesn't set it is unaffected.

    Only the leading `provider:` marker is stripped from `model`, so a gateway
    id that itself contains a slash survives intact
    (``openai:openai/text-embedding-3-small`` -> ``openai/text-embedding-3-small``).
    """
    if model.startswith("fake:"):
        return FakeEmbedder(dim=8)

    if model.startswith("openai:"):
        from langchain_openai import OpenAIEmbeddings
        model_name = model.split(":", 1)[1]
        kwargs: dict = {"model": model_name, "api_key": api_key}
        if timeout is not None:
            kwargs["timeout"] = timeout
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        if base_url:
            kwargs["base_url"] = base_url
        emb = OpenAIEmbeddings(**kwargs)
        return LangChainEmbedder(emb, dim=embedding_dim(model))

    if model.startswith("voyage:"):
        from langchain_community.embeddings.voyageai import VoyageEmbeddings
        model_name = model.split(":", 1)[1]
        emb = VoyageEmbeddings(model=model_name, voyage_api_key=api_key)
        return LangChainEmbedder(emb, dim=embedding_dim(model))

    raise ValueError(f"Unsupported embedding model: {model}")
