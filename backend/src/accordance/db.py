from contextlib import contextmanager

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from accordance.config import Settings

SCHEMA_VERSION = "2"

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

-- users is created FIRST: reports/runs/sessions carry FKs to users(id), and
-- Postgres requires the referenced table to exist at CREATE TABLE time (unlike
-- the FK's row-level check, which is deferred to insert).
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    is_admin      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reports (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ NULL,
    created_by  INTEGER NULL REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS reports_created_by_idx ON reports(created_by);

CREATE TABLE IF NOT EXISTS runs (
    id                    TEXT PRIMARY KEY,
    report_id             TEXT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    parent_run_id         TEXT NULL REFERENCES runs(id) ON DELETE SET NULL,
    version_number        INTEGER NOT NULL,
    kind                  TEXT NOT NULL CHECK (kind IN ('initial','retry','fork','update')),
    reused_from_run_id    TEXT NULL REFERENCES runs(id) ON DELETE SET NULL,
    pdf_filename          TEXT NOT NULL,
    pdf_sha256            TEXT NOT NULL,
    pdf_path              TEXT NOT NULL,
    uploaded_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at          TIMESTAMPTZ NULL,
    status                TEXT NOT NULL,
    error                 TEXT NULL,
    langgraph_thread_id   TEXT NULL,
    selected_disclosures  TEXT NULL,
    created_by            INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    UNIQUE (report_id, version_number)
);
CREATE INDEX IF NOT EXISTS runs_report_id_idx ON runs(report_id);
CREATE INDEX IF NOT EXISTS runs_pdf_sha256_idx ON runs(pdf_sha256);
CREATE INDEX IF NOT EXISTS runs_created_by_idx ON runs(created_by);

CREATE TABLE IF NOT EXISTS chunks (
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id    TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    page      INTEGER NOT NULL,
    text      TEXT NOT NULL,
    text_tsv  tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
CREATE INDEX IF NOT EXISTS chunks_run_id_idx ON chunks(run_id);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING gin (text_tsv);

CREATE TABLE IF NOT EXISTS findings (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id                TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    disclosure_id         TEXT NOT NULL,
    standard              TEXT NOT NULL,
    status                TEXT NOT NULL CHECK (status IN ('covered','partial','missing','error')),
    note                  TEXT NOT NULL,
    evidence_excerpt      TEXT NULL,
    evidence_page         INTEGER NULL,
    elements_json         TEXT NOT NULL,
    suggested_fix         TEXT NOT NULL,
    vision_fallback_used  BOOLEAN NOT NULL DEFAULT FALSE,
    prompt_hash           TEXT NULL,
    score                 INTEGER NULL CHECK (score IS NULL OR score BETWEEN 0 AND 5),
    na_reason             TEXT NULL,
    UNIQUE(run_id, disclosure_id)
);
CREATE INDEX IF NOT EXISTS findings_run_id_idx ON findings(run_id);

CREATE TABLE IF NOT EXISTS judge_traces (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id             TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    disclosure_id      TEXT NOT NULL,
    attempt            INTEGER NOT NULL DEFAULT 1,
    rejudged           BOOLEAN NOT NULL DEFAULT FALSE,
    prompt_hash        TEXT NOT NULL,
    model              TEXT NOT NULL,
    queries_json       TEXT NOT NULL,
    chunk_ids_json     TEXT NOT NULL,
    distances_json     TEXT NOT NULL,
    pages_json         TEXT NOT NULL,
    parse_path         TEXT NOT NULL,
    error              TEXT NULL,
    latency_ms         INTEGER NULL,
    evidence_verified  BOOLEAN NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS judge_traces_run_disc_idx ON judge_traces(run_id, disclosure_id);

CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assessor_corrections (
    id                       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id                   TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    disclosure_id            TEXT NOT NULL,
    standard                 TEXT NOT NULL,
    corrected_score          INTEGER NOT NULL CHECK (corrected_score BETWEEN 0 AND 5),
    corrected_elements_json  TEXT NULL,
    rationale                TEXT NOT NULL,
    agent_score              INTEGER NULL,
    agent_status             TEXT NULL,
    prompt_hash              TEXT NULL,
    model                    TEXT NULL,
    chunk_ids_json           TEXT NOT NULL DEFAULT '[]',
    pages_json               TEXT NOT NULL DEFAULT '[]',
    reviewer                 TEXT NOT NULL,
    superseded               BOOLEAN NOT NULL DEFAULT FALSE,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS corr_run_disc_idx ON assessor_corrections(run_id, disclosure_id);
CREATE INDEX IF NOT EXISTS corr_live_idx ON assessor_corrections(run_id, superseded);

CREATE TABLE IF NOT EXISTS llm_usage (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id         TEXT NULL,
    user_id        INTEGER NULL,
    kind           TEXT NOT NULL,
    model          TEXT NOT NULL,
    input_tokens   INTEGER NOT NULL DEFAULT 0,
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_usd       DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Cache split, added after the table shipped: input_tokens stays the TOTAL and
-- these are SUBSETS of it. Rows written before this existed keep 0/0, so their
-- cost_usd over-counts by whatever was actually cached — history can't be
-- recomputed because the split was never recorded.
ALTER TABLE llm_usage ADD COLUMN IF NOT EXISTS cached_input_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE llm_usage ADD COLUMN IF NOT EXISTS cache_write_tokens INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS llm_usage_user_idx ON llm_usage(user_id);
CREATE INDEX IF NOT EXISTS llm_usage_run_idx ON llm_usage(run_id);

CREATE TABLE IF NOT EXISTS run_completions (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id        TEXT NULL,
    user_id       INTEGER NULL,
    completed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id)
);
CREATE INDEX IF NOT EXISTS run_completions_user_idx ON run_completions(user_id);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);
"""

_pool: ConnectionPool | None = None


def _configure(conn: psycopg.Connection) -> None:
    conn.autocommit = True
    conn.row_factory = dict_row
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    conn.execute("SET hnsw.ef_search = 100")
    try:
        conn.execute("SET hnsw.iterative_scan = strict_order")
    except psycopg.errors.Error:
        pass


def _add_connect_timeout(conninfo: str, timeout_s: int) -> str:
    """Append `connect_timeout=N` to a libpq connection URL/DSN if absent.

    libpq's default connect_timeout is 0 (indefinite). Without an explicit
    timeout the blocking select inside libpq's non-blocking handshake can
    stall pool worker threads indefinitely on some platforms (observed on
    Windows with psycopg-binary). Injecting a reasonable ceiling here means
    the pool reports a clean error instead of wedging the process.
    """
    if "connect_timeout" in conninfo:
        return conninfo
    sep = "&" if "?" in conninfo else "?"
    return f"{conninfo}{sep}connect_timeout={timeout_s}"


def init_pool(settings: Settings) -> ConnectionPool:
    global _pool
    if _pool is not None:
        return _pool
    conninfo = _add_connect_timeout(settings.database_url, settings.db_connect_timeout)
    _pool = ConnectionPool(
        conninfo=conninfo,
        min_size=settings.db_pool_min_size,
        max_size=settings.effective_pool_max_size,
        configure=_configure,
        open=True,
        timeout=30.0,
    )
    return _pool


def get_pool() -> ConnectionPool:
    if _pool is None:
        raise RuntimeError("connection pool not initialized; call init_pool() at startup")
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connection():
    """Borrow a pooled connection (autocommit, dict_row, pgvector-registered)."""
    with get_pool().connection() as conn:
        yield conn


def connect_direct(settings: Settings) -> psycopg.Connection:
    """Standalone connection for CLI / eval / tests. Caller must close()."""
    conninfo = _add_connect_timeout(settings.database_url, settings.db_connect_timeout)
    conn = psycopg.connect(conninfo, autocommit=True, row_factory=dict_row)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    conn.execute("SET hnsw.ef_search = 100")
    try:
        conn.execute("SET hnsw.iterative_scan = strict_order")
    except psycopg.errors.Error:
        pass
    return conn


def _get_meta(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_meta WHERE key=%s", (key,)).fetchone()
    return row["value"] if row else None


def _set_meta(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (%s, %s) "
        "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
        (key, value),
    )


def ensure_schema(conn) -> None:
    try:
        row = conn.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()
        if row is not None and row["value"] == SCHEMA_VERSION:
            return
    except psycopg.errors.UndefinedTable:
        pass
    for stmt in SCHEMA_SQL.split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    _set_meta(conn, "schema_version", SCHEMA_VERSION)


def ensure_embedding_dim(conn, dim: int) -> None:
    """Add/repair the chunks.embedding vector(dim) column + HNSW index. On a dim
    change, clear derived data and mark finished runs failed (the user clicks
    Retry to re-analyze)."""
    current = _get_meta(conn, "embedding_dim")
    has_col = (
        conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='chunks' AND column_name='embedding'"
        ).fetchone()
        is not None
    )

    if has_col and current is not None and int(current) != dim:
        with conn.transaction():
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM findings")
            conn.execute("DELETE FROM judge_traces")
            conn.execute("DROP INDEX IF EXISTS chunks_embedding_hnsw")
            conn.execute("ALTER TABLE chunks DROP COLUMN embedding")
            conn.execute(
                "UPDATE runs SET status='failed', completed_at=NULL, "
                "error='Embedding model changed; cleared old vectors. "
                "Click Retry to re-analyze.' WHERE status IN ('completed','failed')"
            )
        has_col = False

    if not has_col:
        conn.execute(f"ALTER TABLE chunks ADD COLUMN embedding vector({dim})")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding vector_cosine_ops)"
    )
    _set_meta(conn, "embedding_dim", str(dim))


def reconcile_orphaned_runs(conn) -> int:
    cur = conn.execute(
        "UPDATE runs SET status='failed', "
        "error='Interrupted by a server restart. Click Retry to re-run.', "
        "completed_at=now() "
        "WHERE status IN ('queued', 'extracting', 'indexing', 'judging')"
    )
    return cur.rowcount
