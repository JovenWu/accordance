from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_model: str = "openai:gpt-5-mini"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_timeout: float = 60.0
    llm_max_retries: int = 2
    llm_reasoning_effort: str = ""
    llm_service_tier: str = ""

    model_prices_json: str = ""

    assessor_name: str = "assessor"

    session_ttl_days: int = 14
    session_cookie_secure: bool = False

    login_max_attempts: int = 10
    login_window_seconds: int = 300

    admin_username: str = ""
    admin_password: str = ""

    max_inflight_runs_per_user: int = 5

    max_request_mb: int = 0

    @property
    def max_request_bytes(self) -> int:
        """Effective request-body ceiling in bytes. Falls back to the upload cap
        plus 8 MB of headroom (multipart boundaries + form fields) when
        max_request_mb is unset (0)."""
        mb = self.max_request_mb if self.max_request_mb > 0 else self.max_upload_mb + 8
        return mb * 1024 * 1024

    embedding_model: str = "openai:text-embedding-3-small"
    openai_api_key: str = ""
    voyage_api_key: str = ""
    embedding_timeout: float = 60.0
    embedding_max_retries: int = 2
    embedding_base_url: str = ""
    embedding_api_key: str = ""

    data_dir: Path = Path("./data")

    database_url: str = ""

    db_pool_min_size: int = 2
    db_pool_max_size: int = 0

    db_connect_timeout: int = 10

    @property
    def effective_pool_max_size(self) -> int:
        """Deadlock-safe pool ceiling.

        Each admitted run holds 1 'spine' connection for its whole lifetime, so
        that term scales with max_concurrent_runs. Judge workers borrow a
        connection only AFTER passing the GLOBAL judge semaphore
        (graph.nodes.judge_all_node), so the number of worker connections in
        flight is capped at judge_concurrency across the entire process — not
        per run. The two therefore ADD; they used to multiply, which demanded
        138 connections for 10 runs x 12 workers (past Postgres' default
        max_connections of 100) to do judge_concurrency calls' worth of work.

        Add headroom for API requests + lifespan.

        Keep this in step with where the semaphore is acquired: if a worker
        ever takes a connection before waiting on it again, demand reverts to
        the multiplied form and an undersized pool DEADLOCKS (runs hold partial
        allocations while waiting on connections the others hold).
        """
        if self.db_pool_max_size > 0:
            return self.db_pool_max_size
        return self.max_concurrent_runs + self.judge_concurrency + 8

    max_upload_mb: int = 100
    judge_concurrency: int = 3

    max_concurrent_runs: int = 4
    shutdown_drain_seconds: float = 25.0

    vision_fallback_enabled: bool = True

    vision_fallback_on_low_confidence: bool = True

    vision_fallback_budget: int = 40

    retrieval_mode: str = "hybrid"

    retrieval_per_element: bool = True

    judge_rejudge_on_missing: bool = True
    judge_structured_method: str = "json_schema"

    retrieval_page_coherent: bool = False

    retrieval_tag_aware: bool = False
    retrieval_tag_limit: int = 5

    rerank_enabled: bool = False
    rerank_model: str = "ms-marco-MultiBERT-L-12"
    rerank_top_n: int = 15
    rerank_threads: int = 2

    score_cutoff_low: float = 0.33
    score_cutoff_high: float = 0.66

    prompt_cache_enabled: bool = False

    extractor_backend: str = "pymupdf"

    docling_batch_size: int = 50

    docling_do_ocr: bool = False
    docling_do_table_structure: bool = False
    docling_timeout_seconds: float = 0.0
    docling_num_threads: int = 1
    docling_images_scale: float = 1.0
    docling_layout_batch_size: int = 1
    docling_ocr_batch_size: int = 1
    docling_table_batch_size: int = 1

    @property
    def pdf_dir(self) -> Path:
        return self.data_dir / "pdfs"


def check_required_keys(settings: Settings) -> list[str]:
    """Return human-readable problems for missing credentials, given the
    configured providers. Empty list = OK.

    ``fake:`` models (tests / offline) need no key. Used at startup to fail fast
    instead of booting healthy and then failing every run deep in the worker
    when a real provider has no API key.
    """
    problems: list[str] = []
    if not settings.database_url:
        problems.append("DATABASE_URL is empty but is required (Postgres connection).")
    if not settings.llm_model.startswith("fake:") and not settings.llm_api_key:
        problems.append(
            f"LLM_API_KEY is empty but LLM_MODEL={settings.llm_model!r} requires a key."
        )
    em = settings.embedding_model
    if not em.startswith("fake:") and not embedding_credentials(settings)[0]:
        provider_key = "OPENAI_API_KEY" if em.startswith("openai:") else "VOYAGE_API_KEY"
        problems.append(
            f"No embedding key: set EMBEDDING_API_KEY (or {provider_key}) "
            f"for EMBEDDING_MODEL={em!r}."
        )
    return problems


def embedding_credentials(settings) -> tuple[str, str]:
    """(api_key, base_url) for the embedder.

    EMBEDDING_API_KEY wins when set; otherwise the key is derived from the
    model's provider, preserving the historical behaviour. The explicit key
    matters when EMBEDDING_BASE_URL points at a third-party gateway: without
    it, the provider key (e.g. OPENAI_API_KEY) would be sent to that gateway.
    """
    if settings.embedding_api_key:
        key = settings.embedding_api_key
    elif settings.embedding_model.startswith("openai:"):
        key = settings.openai_api_key
    else:
        key = settings.voyage_api_key
    return key, settings.embedding_base_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-memoized Settings.

    Wired as a FastAPI ``Depends`` on ~25 endpoints AND called dozens of times
    per run in the judge hot loop. Constructing ``Settings()`` re-reads ``.env``
    from disk and re-parses the environment each time, so without the cache the
    .env file is read on every request (including the 4s status pollers) and
    ~hundreds of times per sector-preset run. The env is fixed for a process's
    lifetime, so one construction is correct. Tests that mutate the environment
    call ``get_settings.cache_clear()`` (wired as an autouse fixture).
    """
    return Settings()


def resolve_pdf_path(stored_path: str, settings: Settings) -> Path:
    """Resolve a persisted ``pdf_path`` to a usable file path.

    ``pdf_path`` is saved as ``str(Path)`` at upload time, which bakes in the
    OS that created the row — a Windows dev DB stores ``data\\pdfs\\<uuid>.pdf``
    (backslashes, relative) which ``fitz.open`` / ``FileResponse`` can't open
    when the same DB is mounted into the Linux container. PDFs always live in
    ``pdf_dir`` under a unique ``<uuid>.pdf`` name, so we normalize separators,
    use the stored path when it already resolves, then fall back to
    ``pdf_dir/<basename>``. Returns the best candidate even when absent so the
    caller can decide (404 / skip vision).
    """
    normalized = Path(stored_path.replace("\\", "/"))
    if normalized.is_file():
        return normalized
    return settings.pdf_dir / normalized.name
