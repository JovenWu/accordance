from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM (judge) — OpenAI by default. llm_base_url is blank so requests go to
    # OpenAI's real endpoint; set it only to route through an OpenAI-compatible
    # proxy.
    # gpt-5-mini default: a judge-model A/B on the PTVI sample cut score MAE
    # 2.50 -> 0.75 vs gpt-4.1-nano and recovered the data-table disclosures the
    # cheap model couldn't read. The judge is a network call (no local CPU), so
    # this doesn't burden constrained servers. Override with LLM_MODEL.
    llm_model: str = "openai:gpt-5-mini"
    llm_base_url: str = ""
    llm_api_key: str = ""
    # Per-request timeout in seconds for the judge LLM. Without this, a
    # hanging endpoint burns ~12-16 s of exponential backoff per retry before
    # the SDK gives up. Override with LLM_TIMEOUT.
    llm_timeout: float = 60.0
    # Maximum SDK-level retries for transient 429/5xx errors. Lowered from the
    # old hardcoded 5 to bound worst-case latency (each retry adds backoff).
    # Override with LLM_MAX_RETRIES.
    llm_max_retries: int = 2
    # How hard the model thinks before answering. Reasoning tokens bill as
    # OUTPUT, so this is a direct cost/latency lever: measured on gpt-5.6-luna
    # over one judge prompt, none=206 output tokens / 7.6 s vs high=729 / 16.0 s.
    # BLANK means the parameter is never sent — non-reasoning models and some
    # OpenAI-compatible proxies reject it, so it stays opt-in. Accepted values
    # are model-specific (luna: none/low/medium/high/xhigh/max; it rejects
    # 'minimal'), so it's passed through unvalidated. Override with
    # LLM_REASONING_EFFORT.
    llm_reasoning_effort: str = ""
    # Processing tier: 'flex' is roughly half price for higher latency,
    # 'priority' the reverse, 'auto' the provider default. Blank sends nothing.
    # Flex can be capacity-refused (429), so build_llm wraps it with a
    # standard-tier fallback — a refusal costs today's price, never a gap in
    # the report. NOTE: an endpoint that doesn't implement tiers may accept the
    # parameter and ignore it (the dev Codex proxy returns service_tier=null
    # even for 'priority'), so confirm the response echoes the tier before
    # trusting the discount. Override with LLM_SERVICE_TIER.
    llm_service_tier: str = ""

    # Optional JSON override for the LLM/embedding price table, merged over
    # accordance.pricing.DEFAULT_PRICES. Keyed by bare model name, USD per 1M
    # tokens: '{"gpt-5-mini": {"in": 0.25, "out": 2.0}}'. Override MODEL_PRICES_JSON.
    model_prices_json: str = ""

    # Name recorded as the reviewer on assessor corrections (single-reviewer
    # Phase 1; no per-user auth yet). Override with ASSESSOR_NAME.
    assessor_name: str = "assessor"

    # Session login. TTL in days for a login session; cookie Secure flag. Secure
    # is also auto-enabled when the request scheme is HTTPS — which behind a
    # TLS-terminating proxy requires uvicorn to honor X-Forwarded-Proto (the
    # Docker CMD passes --proxy-headers). For a production HTTPS deployment set
    # SESSION_COOKIE_SECURE=true explicitly so the cookie is never issued
    # without Secure even if the proxy doesn't forward the scheme. Override
    # SESSION_TTL_DAYS / SESSION_COOKIE_SECURE.
    session_ttl_days: int = 14
    session_cookie_secure: bool = False

    # Login throttling (defense against online brute force / credential
    # stuffing). An attacker gets at most `login_max_attempts` FAILED logins per
    # `login_window_seconds`, counted per client IP AND per username; further
    # attempts return 429 (and skip the expensive PBKDF2 verify) until the
    # window rolls off. A successful login clears the counters. Set
    # LOGIN_MAX_ATTEMPTS=0 to disable (not advised in production). Override
    # LOGIN_MAX_ATTEMPTS / LOGIN_WINDOW_SECONDS.
    login_max_attempts: int = 10
    login_window_seconds: int = 300

    # Admin bootstrap ("set up on build"). When ADMIN_USERNAME is set, the
    # startup lifespan ensures that account exists as an ACTIVE ADMIN. The
    # password is applied on creation and re-asserted on every boot when
    # ADMIN_PASSWORD is non-empty (declarative rotation via .env); leaving it
    # empty after first boot keeps the existing password. The bootstrap password
    # must be >= 8 chars or the account is not created. NOTE: this value is
    # readable in the container environment — use a strong secret. Override
    # ADMIN_USERNAME / ADMIN_PASSWORD.
    admin_username: str = ""
    admin_password: str = ""

    # Per-user concurrency quota: the max number of runs a single user may have
    # in-flight (queued/extracting/indexing/judging) at once. Caps unbounded
    # worker-thread spawn and runaway paid-LLM spend from a looping or
    # compromised account; excess run-creating requests return 429. 0 disables.
    # Override MAX_INFLIGHT_RUNS_PER_USER.
    max_inflight_runs_per_user: int = 5

    # Hard ceiling (MB) on the HTTP request body the server accepts, enforced at
    # the ASGI layer from Content-Length BEFORE the body is spooled to disk — so
    # an oversized upload is refused at the door, not after buffering it. 0 =>
    # derive from max_upload_mb + headroom for multipart framing. When you front
    # the app with a reverse proxy, set its client_max_body_size to match.
    # Override MAX_REQUEST_MB.
    max_request_mb: int = 0

    @property
    def max_request_bytes(self) -> int:
        """Effective request-body ceiling in bytes. Falls back to the upload cap
        plus 8 MB of headroom (multipart boundaries + form fields) when
        max_request_mb is unset (0)."""
        mb = self.max_request_mb if self.max_request_mb > 0 else self.max_upload_mb + 8
        return mb * 1024 * 1024

    # Embeddings
    embedding_model: str = "openai:text-embedding-3-small"
    openai_api_key: str = ""
    voyage_api_key: str = ""
    # Per-request timeout (s) and SDK retry cap for the embedding API. Without
    # these, a stalled/throttling endpoint can hang the indexing step — and the
    # DB connection it holds — unbounded. Mirrors the judge LLM's settings.
    # Override with EMBEDDING_TIMEOUT / EMBEDDING_MAX_RETRIES.
    embedding_timeout: float = 60.0
    embedding_max_retries: int = 2
    # Optional OpenAI-compatible gateway for EMBEDDINGS only (OpenRouter,
    # LiteLLM, ...). Deliberately separate from LLM_BASE_URL: the judge and the
    # embedder can sit on different accounts, and assuming one base URL covered
    # both is what hid a dead embedding key behind "judge failed" errors.
    # Blank = straight to the provider (production default). Override with
    # EMBEDDING_BASE_URL.
    embedding_base_url: str = ""
    # Key for that gateway. Blank falls back to the provider-derived key
    # (OPENAI_API_KEY / VOYAGE_API_KEY) — which means setting EMBEDDING_BASE_URL
    # ALONE sends your OpenAI/Voyage key to that third-party gateway. Set this
    # whenever the base URL is not the provider's own endpoint.
    # Override with EMBEDDING_API_KEY.
    embedding_api_key: str = ""

    data_dir: Path = Path("./data")

    # PostgreSQL connection. Driver-agnostic libpq URL, e.g.
    # postgresql://gri:gri@db:5432/gri. Single source of truth for the datastore;
    # point it at a managed instance to move off the compose service.
    database_url: str = ""

    # Connection-pool bounds. max is auto-derived (see effective_pool_max_size)
    # when db_pool_max_size == 0 so it can never be smaller than the worst-case
    # concurrent-connection demand (which would deadlock the judge fan-out).
    db_pool_min_size: int = 2
    db_pool_max_size: int = 0

    # Per-connection timeout (seconds) passed to libpq when the pool opens a
    # new connection. libpq's default is 0 (indefinite); without a timeout the
    # blocking select inside libpq's non-blocking handshake can stall pool
    # worker threads indefinitely on some platforms (observed on Windows).
    # 10 s is ample for a local/LAN instance; raise it for high-latency links.
    # Override with DB_CONNECT_TIMEOUT.
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

    # Max accepted PDF upload size (MB). Uploads are read into memory to hash +
    # persist, so an unbounded read is a memory-exhaustion DoS. 100 MB covers a
    # very large sustainability report; lower it to tighten the bound. Override
    # with MAX_UPLOAD_MB.
    max_upload_mb: int = 100
    judge_concurrency: int = 3

    # Admission control: max run-worker threads executing concurrently. Each run
    # opens up to `judge_concurrency` Postgres connections, so unbounded run
    # fan-out under an upload burst can exhaust the connection pool. Excess
    # runs queue (their thread parks on the semaphore before opening any
    # connection). Override with MAX_CONCURRENT_RUNS.
    max_concurrent_runs: int = 4
    # On shutdown (SIGTERM / docker stop / deploy), how long to spend cancelling
    # and joining in-progress run workers before exiting, so a run isn't killed
    # mid-write. Keep < the container's stop_grace_period. Override with
    # SHUTDOWN_DRAIN_SECONDS.
    shutdown_drain_seconds: float = 25.0

    vision_fallback_enabled: bool = True

    # The text judge only self-flags `needs_vision_fallback` when it sees an
    # explicit "see chart" hint — but on professionally-designed reports the
    # data is locked in table-IMAGES that extraction flattens into garbled
    # text, so the judge thinks it has the data and never asks for vision.
    # When this is on, ANY 'partial' or 'missing' verdict is re-judged with
    # vision (rendering the candidate pages), which recovers numbers the text
    # pass couldn't read. Set false to only escalate on the LLM's self-flag.
    vision_fallback_on_low_confidence: bool = True

    # Per-run cap on vision re-judge calls — a cost/latency guard, since each
    # vision call renders up to 3 page images. 40 comfortably covers the v1
    # KB (38 disclosures); lower it to bound spend on image-heavy reports.
    vision_fallback_budget: int = 40

    # Retrieval strategy:
    #   hybrid (default) — fuse dense (pgvector) + BM25 (Postgres FTS) via RRF
    #   dense            — cosine kNN only (pre-hybrid baseline)
    #   bm25             — lexical only (diagnostic)
    retrieval_mode: str = "hybrid"

    # Expand each disclosure's retrieval queries with its required_element
    # descriptions. Catches cross-page disclosures (e.g., legal_name on
    # page 4 and countries_of_operation on page 80 in GRI 2-1). Increases
    # per-judge token cost by ~30-50%. Set to false to A/B against the
    # disclosure-queries-only baseline.
    retrieval_per_element: bool = True

    # When the first judge pass returns 'missing', retry once with the
    # disclosure's element descriptions as additional retrieval queries
    # (and 2x k). Cuts false negatives at the cost of +1 LLM call per
    # disclosure-that-would-have-been-missing.
    judge_rejudge_on_missing: bool = True
    # How the judge asks for structured output. 'json_schema' makes the
    # PROVIDER constrain decoding to the schema, so an invalid enum can't be
    # generated (observed: status="found", the ELEMENT vocabulary, which failed
    # 3 disclosures in a 150-disclosure run). OpenAI direct and OpenRouter both
    # support it, so PRODUCTION NEEDS NO CHANGE. Set 'function_calling' only for
    # a proxy that rejects json_schema — otherwise every disclosure burns a
    # failed call plus a fallback call. Override with JUDGE_STRUCTURED_METHOD.
    judge_structured_method: str = "json_schema"

    # Page-coherent sibling swap: after the normal top-k merge, look up chunks
    # that share a page with the top-ranked hits but were not retrieved (e.g. a
    # table chunk that embeds poorly). Each such sibling is swapped in for the
    # weakest current member, keeping pool size CONSTANT (cost-neutral).
    # Sibling text is truncated to the displaced member's length when longer,
    # so per-call token count never grows.
    # DEFAULT OFF: an isolated text-path A/B against the PTVI ground truth
    # (2026-06-22) found the swap was a wash — its effect was within the judge's
    # run-to-run noise floor and marginally negative on a numeric disclosure
    # (it can dilute the top-k). The real accuracy lever is judge calibration
    # (systematic "partial"-when-"covered"), not retrieval. Kept behind this
    # flag (set true to re-enable / re-evaluate).
    retrieval_page_coherent: bool = False

    # Tag-aware retrieval: force-include chunks that cite the disclosure's own
    # GRI tag (e.g. "[[GRI 303-4]]"). Reports self-label their data tables, so
    # this surfaces appendix tables the semantic/rerank pass misses.
    # IMPORTANT — only beneficial WITH docling_do_table_structure=true (clean
    # tables). On garbled picture-text tables it surfaces unreadable tables that
    # add noise: measured -5pp alone, but +5pp when paired with table-structure
    # ("high-accuracy mode"). Default off; enable BOTH together or neither.
    retrieval_tag_aware: bool = False
    retrieval_tag_limit: int = 5

    # Reranker (FlashRank) over the unioned candidate pool. Deterministic.
    # Default OFF: an on/off A/B on the PTVI gold (n=29) showed no accuracy
    # benefit (MAE 1.93 off vs 1.97 on; recall 23 vs 22; score changes symmetric
    # 6 up / 6 down) — retrieval is not the bottleneck, the judge is. Keeping it
    # off removes the onnxruntime CPU load on constrained servers. Re-enable with
    # RERANK_ENABLED=true (threads are capped via rerank_threads either way).
    rerank_enabled: bool = False
    rerank_model: str = "ms-marco-MultiBERT-L-12"
    rerank_top_n: int = 15
    # Cap the FlashRank reranker's onnxruntime CPU threads. onnxruntime defaults
    # to one intra-op thread per core, which pins every core during per-disclosure
    # reranking; 2 keeps a dev laptop and a low-core production server responsive.
    rerank_threads: int = 2

    # 0-5 grading cutoffs: f = mean element weight (found=1, partial=0.5,
    # missing=0). f==0 -> 1; <=low -> 2; <=high -> 3; <1.0 -> 4; ==1.0 -> 5.
    # Tunable on the eval set; defaults are reasonable, not sourced constants.
    score_cutoff_low: float = 0.33
    score_cutoff_high: float = 0.66

    # Attach an Anthropic cache_control breakpoint to the stable judge system
    # prompt. Only helps if the LLM proxy forwards it; default off until verified.
    prompt_cache_enabled: bool = False

    # PDF extractor backend:
    #   pymupdf (default) — fast, low-memory, embedded-text only. ~50x
    #     faster than Docling on long PDFs; no `std::bad_alloc` risk.
    #     Use this unless you specifically need OCR or ML layout.
    #   docling           — ML-based pipeline (layout + optional OCR +
    #     table structure). Higher memory cost; required for scanned
    #     PDFs (set DOCLING_DO_OCR=true alongside).
    extractor_backend: str = "pymupdf"

    # Docling extracts long PDFs in fixed-size batches and recreates the
    # converter between batches. Defeats the C++ heap fragmentation that
    # causes `std::bad_alloc` on 200+ page PDFs even when system RAM is
    # plentiful — each batch starts with a clean allocator state. Set to
    # 0 to disable batching (single-pass; matches the pre-batch behavior).
    docling_batch_size: int = 50

    # Per-page memory dominated by: (a) page bitmap rendered for layout
    # detection, (b) RapidOCR tensors, (c) TableFormer cell predictions.
    # We default to the cheapest configuration that still works for
    # sustainability reports (text-PDFs with embedded text and tables
    # whose cell layout we can read from the text stream). Flip the OCR
    # and table flags on if you're processing a scanned PDF or you need
    # cell-accurate table structure.
    docling_do_ocr: bool = False
    docling_do_table_structure: bool = False
    # Wall-clock budget (seconds) for a single Docling conversion pass; 0
    # disables it (default — no behavior change). When set, a pass that exceeds
    # this raises a clear ExtractionTimeoutError instead of letting a
    # pathological PDF grind unbounded. The native work is abandoned (not killed
    # in-process); the container mem_limit is the OOM backstop. Override with
    # DOCLING_TIMEOUT_SECONDS.
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
    # Ask the SAME helper the runtime uses, so validation can't demand a key the
    # embedder would never have used. EMBEDDING_API_KEY legitimately replaces the
    # provider key when embeddings are routed through a gateway; checking
    # OPENAI_API_KEY directly here hard-failed startup on a valid config.
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
