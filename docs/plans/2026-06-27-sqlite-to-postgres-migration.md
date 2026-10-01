# SQLite → PostgreSQL Migration + Per-User Ownership — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all persistence from SQLite (with sqlite-vec + FTS5) to PostgreSQL (psycopg3 + pgvector + native full-text search), starting fresh with no data migration, and make run history per-user (reports owned by their creator; admins see all).

**Architecture:** A process-wide `psycopg_pool.ConnectionPool` owns all DB connections behind the existing `_open_conn()` seam; schema is created once at startup. Chunks fold their vector and full-text into the `chunks` table (`embedding vector(dim)` + `text_tsv tsvector`), replacing the vec0 and FTS5 virtual tables. The in-process thread-per-run worker and local-disk PDFs are unchanged. Ownership is enforced by a `reports.created_by` column plus access-check helpers applied to every report/run endpoint.

**Tech Stack:** Python 3.11–3.13, FastAPI, psycopg 3 (`psycopg[binary]`, `psycopg_pool`), `pgvector`, PostgreSQL 16 (`pgvector/pgvector:pg16`), pytest.

**Reference spec:** `docs/specs/2026-06-27-sqlite-to-postgres-design.md` (read it first).

**Branch:** `feat/postgres-migration` (already created; `main` stays on SQLite until merge).

## Global Constraints

- **Python:** `requires-python = ">=3.11,<3.14"`. Dependency pins keep a floor + capped next-major (e.g. `psycopg[binary]>=3.2,<4.0`), matching the existing `pyproject.toml` convention.
- **Lint:** ruff `line-length = 100`, `select = ["E","F","I","B","UP","RUF"]`. Run `ruff check` + `ruff format` before each commit. Product code (`src`) stays strict; tests may use the existing per-file ignores.
- **Use the venv interpreter `backend/.venv/Scripts/python`** (Python 3.13). The bare `python` on PATH is 3.10 (too old). Run pytest from the `backend/` directory (its `pyproject.toml` holds the pytest config: `pythonpath=["src"]`, `testpaths=["tests"]`). Example: `cd backend && .venv/Scripts/python -m pytest tests/test_db.py -v`.
- **Tests run TARGETED locally, never the whole suite at once** (full `pytest` hangs on this machine — process accumulation). Always run specific files/nodes.
- **CI exists** (`.github/workflows/ci.yml`): the backend job runs `pytest -q -p no:cacheprovider --timeout=300` from `backend/`. It currently has **no Postgres service**, so this migration MUST add a `pgvector/pgvector` service + `TEST_DATABASE_URL` to that job (Task 13) or CI goes red on the PG-dependent tests.
- **Frontend type-check is `npm run build`** (`npx tsc --noEmit` is a no-op here due to project refs).
- **Postgres for tests:** host-run `pytest` connects via `TEST_DATABASE_URL` (the conftest prefers it over `DATABASE_URL`). **Use `127.0.0.1`, NOT `localhost`** — the `db` service binds IPv4 loopback only, and on Windows `localhost` resolves to IPv6 `::1` first, costing a ~10–15s `connect_timeout` per connection before it falls back. On this dev machine: `TEST_DATABASE_URL=postgresql://gri:gri@127.0.0.1:5433/gri` (`DB_HOST_PORT=5433` because 5432 was taken; container always listens on 5432). The in-container `DATABASE_URL` uses host `db` (compose network) which does NOT resolve from the host. Bring the DB up first: `docker compose up -d db`. The `vector` extension is auto-created on connect. (Linux/CI `localhost` → 127.0.0.1, so CI is unaffected.)
- **Placeholders are `%s`** (psycopg3 has no `?` support). Dynamic placeholder builders that emit `"?"` must emit `"%s"`.
- **Row access is by column name** (`row["id"]`), never positional (`row[0]`) — `dict_row` has no integer indexing.
- **Autocommit is ON** for pooled connections; multi-statement atomic writes use `with conn.transaction():`.
- **Start fresh:** no ETL, no v1→v7 migration code. The admin account re-bootstraps from `.env`.

---

# PHASE 1 — PostgreSQL datastore port

## Task 1: Dependencies, settings, compose service, env

**Files:**
- Modify: `backend/pyproject.toml` (deps)
- Modify: `backend/src/accordance/config.py` (settings)
- Modify: `docker-compose.yml` (add `db` service)
- Modify: `.env.example`
- Modify: `Dockerfile` (drop nothing required, but confirm psycopg binary works)
- Test: `backend/tests/test_config_database_url.py` (create)

**Interfaces:**
- Produces: `Settings.database_url: str`, `Settings.db_pool_min_size: int`, `Settings.db_pool_max_size: int`, and a computed `Settings.effective_pool_max_size` property. Removes `Settings.db_path`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_config_database_url.py
import importlib

from accordance.config import Settings, get_settings


def test_database_url_read_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/gri")
    get_settings.cache_clear()
    s = Settings()
    assert s.database_url == "postgresql://u:p@localhost:5432/gri"


def test_effective_pool_max_derives_from_concurrency(monkeypatch):
    monkeypatch.delenv("DB_POOL_MAX_SIZE", raising=False)
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "4")
    monkeypatch.setenv("JUDGE_CONCURRENCY", "3")
    get_settings.cache_clear()
    s = Settings()
    # 4 * (1 + 3) + 8 headroom = 24
    assert s.effective_pool_max_size == 24


def test_db_path_attribute_removed():
    assert not hasattr(Settings(), "db_path")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_config_database_url.py -v`
Expected: FAIL (`database_url` / `effective_pool_max_size` not defined).

- [ ] **Step 3: Edit `config.py`**

Add to `Settings` (place near `data_dir`):

```python
    # PostgreSQL connection. Driver-agnostic libpq URL, e.g.
    # postgresql://gri:gri@db:5432/gri. Single source of truth for the datastore;
    # point it at a managed instance to move off the compose service.
    database_url: str = ""

    # Connection-pool bounds. max is auto-derived (see effective_pool_max_size)
    # when db_pool_max_size == 0 so it can never be smaller than the worst-case
    # concurrent-connection demand (which would deadlock the judge fan-out).
    db_pool_min_size: int = 2
    db_pool_max_size: int = 0

    @property
    def effective_pool_max_size(self) -> int:
        """Deadlock-safe pool ceiling. A run holds 1 'spine' connection plus up
        to judge_concurrency worker connections, and admission is capped at
        max_concurrent_runs, so every admitted run must be able to acquire all
        of its connections. Add headroom for API requests + lifespan."""
        if self.db_pool_max_size > 0:
            return self.db_pool_max_size
        return self.max_concurrent_runs * (1 + self.judge_concurrency) + 8
```

Remove the `db_path` property:

```python
    # DELETE these lines:
    # @property
    # def db_path(self) -> Path:
    #     return self.data_dir / "gri.db"
```

Add `DATABASE_URL` validation in `check_required_keys`:

```python
    if not settings.database_url:
        problems.append("DATABASE_URL is empty but is required (Postgres connection).")
```

- [ ] **Step 4: Edit `backend/pyproject.toml` dependencies**

Remove these two lines:

```
  "langgraph-checkpoint-sqlite>=3.0,<4.0",
  "sqlite-vec>=0.1.6,<0.2",
```

Add:

```
  "psycopg[binary]>=3.2,<4.0",
  "psycopg-pool>=3.2,<4.0",
  "pgvector>=0.3,<1.0",
```

Install: `pip install -e backend[dev]` (or `uv pip install -e ...`).

- [ ] **Step 5: Add the `db` service to `docker-compose.yml`**

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    container_name: accordance-db
    restart: unless-stopped
    environment:
      POSTGRES_USER: gri
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-gri}
      POSTGRES_DB: gri
    ports:
      - "127.0.0.1:5432:5432"   # host-loopback only — lets host-run pytest/dev reach PG
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U gri -d gri"]
      interval: 10s
      timeout: 5s
      retries: 5
  app:
    # ... existing app config ...
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATA_DIR: /app/data
      DATABASE_URL: postgresql://gri:${POSTGRES_PASSWORD:-gri}@db:5432/gri
volumes:
  pgdata:
```

Remove the host bind for the SQLite file if any; keep `- ./data:/app/data` (PDFs + health probe still live there).

- [ ] **Step 6: Update `.env.example`**

Add under the datastore section:

```
# PostgreSQL connection (the app's datastore). The compose `db` service uses these.
POSTGRES_PASSWORD=gri
DATABASE_URL=postgresql://gri:gri@db:5432/gri   # inside compose; use localhost:5432 for host-run dev
```

- [ ] **Step 7: Run config tests + bring up Postgres to verify the extension**

Run: `pytest backend/tests/test_config_database_url.py -v`
Expected: PASS.

Run: `docker compose up -d db` then
`docker compose exec db psql -U gri -d gri -c "CREATE EXTENSION IF NOT EXISTS vector; SELECT extname FROM pg_extension WHERE extname='vector';"`
Expected: prints `vector`.

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/src/accordance/config.py docker-compose.yml .env.example backend/tests/test_config_database_url.py
git commit -m "feat(db): add Postgres deps, DATABASE_URL settings, and compose pgvector service"
```

---

## Task 2: Rewrite `db.py` — pool, connection management, canonical PG schema

**Files:**
- Rewrite: `backend/src/accordance/db.py`
- Test: `backend/tests/test_db.py` (rewrite), `backend/tests/test_db_reconcile.py` (port)

**Interfaces:**
- Produces:
  - `init_pool(settings) -> ConnectionPool` — build + open the process pool (idempotent).
  - `get_pool() -> ConnectionPool` — the live pool (raises if not initialized).
  - `connection()` — context manager yielding a pooled `psycopg.Connection` (dict_row, pgvector-registered, autocommit).
  - `connect_direct(settings) -> psycopg.Connection` — a standalone (non-pooled) connection for CLI/eval; caller closes it.
  - `close_pool() -> None` — close at shutdown.
  - `ensure_schema(conn) -> None` — idempotent canonical DDL, gated by `app_meta.schema_version` (= `"1"`).
  - `ensure_embedding_dim(conn, dim) -> None` — create/alter the `chunks.embedding` column + HNSW index to `dim`; self-heal on dim change (clear chunks/findings/judge_traces, mark runs failed).
  - `reconcile_orphaned_runs(conn) -> int` — unchanged behavior, `%s` placeholders.
- Removes: `connect`, `load_vec_extension`, `ensure_vec_schema`, `_migrate_v1_to_v2`, `_apply_pre_schema_migrations`, `_apply_post_schema_migrations`, all PRAGMA/`sqlite_master`/`PRAGMA table_info` logic, `import sqlite3`, `import sqlite_vec`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_db.py  (REPLACE FILE)
import os

import pytest

from accordance.config import get_settings
from accordance import db


@pytest.fixture
def conn():
    # Uses TEST_DATABASE_URL (or DATABASE_URL) against a real Postgres.
    get_settings.cache_clear()
    s = get_settings()
    c = db.connect_direct(s)
    db.ensure_schema(c)
    db.ensure_embedding_dim(c, dim=8)
    # clean slate
    c.execute("TRUNCATE reports, runs, chunks, findings, judge_traces, "
              "assessor_corrections, llm_usage, run_completions, users, sessions "
              "RESTART IDENTITY CASCADE")
    yield c
    c.close()


def test_ensure_schema_is_idempotent(conn):
    # Running twice must not error and must leave all core tables present.
    db.ensure_schema(conn)
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    ).fetchall()
    names = {r["table_name"] for r in rows}
    assert {"reports", "runs", "chunks", "findings", "judge_traces",
            "app_meta", "assessor_corrections", "llm_usage",
            "run_completions", "users", "sessions"} <= names


def test_schema_version_recorded(conn):
    row = conn.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()
    assert row["value"] == db.SCHEMA_VERSION


def test_chunks_has_vector_and_tsv_columns(conn):
    cols = {r["column_name"]: r["data_type"] for r in conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name='chunks'").fetchall()}
    assert "embedding" in cols          # pgvector type (USER-DEFINED)
    assert cols["text_tsv"] == "tsvector"


def test_is_active_is_boolean(conn):
    col = conn.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name='users' AND column_name='is_active'").fetchone()
    assert col["data_type"] == "boolean"
```

```python
# backend/tests/test_db_reconcile.py  (PORT — change placeholders + fixture)
def test_reconcile_marks_inflight_failed(conn):
    conn.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                 ("u", "x"))
    conn.execute("INSERT INTO reports (id, name) VALUES (%s, %s)", ("rep1", "r"))
    conn.execute(
        "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
        "pdf_sha256, pdf_path, status) VALUES "
        "(%s, %s, 1, 'initial', 'f.pdf', 'sha', 'p', 'judging')",
        ("run1", "rep1"))
    from accordance.db import reconcile_orphaned_runs
    n = reconcile_orphaned_runs(conn)
    assert n == 1
    assert conn.execute("SELECT status FROM runs WHERE id='run1'").fetchone()["status"] == "failed"
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest backend/tests/test_db.py -v`
Expected: FAIL (imports `connect_direct`, `ensure_embedding_dim` missing).

- [ ] **Step 3: Write the new `db.py`**

```python
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pgvector.psycopg import register_vector
from contextlib import contextmanager

from accordance.config import Settings

SCHEMA_VERSION = "1"

# Canonical Postgres schema. Idempotent (CREATE ... IF NOT EXISTS). The vec0 and
# FTS5 virtual tables are gone: chunks carries `embedding vector(dim)` (added by
# ensure_embedding_dim, since the dim isn't known until the embedder is chosen)
# and a generated `text_tsv` tsvector. Integer 0/1 flags are real BOOLEAN.
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
    # The pgvector `vector` type must exist before register_vector() can look up
    # its OID. On a brand-new DB the extension isn't installed yet, and this
    # runs on EVERY connection checkout, so create it idempotently here (cheap;
    # IF NOT EXISTS short-circuits once present).
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)


def init_pool(settings: Settings) -> ConnectionPool:
    global _pool
    if _pool is not None:
        return _pool
    _pool = ConnectionPool(
        conninfo=settings.database_url,
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
    conn = psycopg.connect(settings.database_url, autocommit=True, row_factory=dict_row)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")  # see _configure note
    register_vector(conn)
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
    # Fast path: once at the current version, skip the DDL.
    try:
        row = conn.execute(
            "SELECT value FROM app_meta WHERE key='schema_version'"
        ).fetchone()
        if row is not None and row["value"] == SCHEMA_VERSION:
            return
    except psycopg.errors.UndefinedTable:
        pass  # app_meta not created yet
    conn.execute(SCHEMA_SQL)
    _set_meta(conn, "schema_version", SCHEMA_VERSION)


def ensure_embedding_dim(conn, dim: int) -> None:
    """Add/repair the chunks.embedding vector(dim) column + HNSW index. On a dim
    change, clear derived data and mark finished runs failed (same UX as the old
    vec0 self-heal: the user clicks Retry)."""
    current = _get_meta(conn, "embedding_dim")
    has_col = conn.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='chunks' AND column_name='embedding'"
    ).fetchone() is not None

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
```

- [ ] **Step 4: Run the db tests**

Run: `pytest backend/tests/test_db.py backend/tests/test_db_reconcile.py -v`
Expected: PASS (Postgres from `TEST_DATABASE_URL`/`DATABASE_URL` must be running).

- [ ] **Step 5: Delete the obsolete SQLite-only tests**

```bash
git rm backend/tests/test_db_vec.py backend/tests/test_db_migration.py \
       backend/tests/db/test_migration_corrections.py \
       backend/tests/db/test_migration_score.py \
       backend/tests/db/test_migration_admin.py \
       backend/tests/db/test_migration_usage.py
```

- [ ] **Step 6: Run ruff + commit**

```bash
ruff check backend/src/accordance/db.py && ruff format backend/src/accordance/db.py
git add backend/src/accordance/db.py backend/tests/test_db.py backend/tests/test_db_reconcile.py
git commit -m "feat(db): Postgres pool + canonical pgvector schema; drop SQLite migration code"
```

---

## Task 3: Test harness — Postgres fixtures

**Files:**
- Modify: `backend/tests/conftest.py` (add pool/db fixtures)
- Modify: `backend/tests/api/conftest.py` (port `auth_client`)
- Test: covered by Task 2 tests running green + a smoke test added here.

**Interfaces:**
- Produces: a `pg` autouse-ish fixture that initializes the pool against `TEST_DATABASE_URL`, ensures schema once per session, and truncates all tables before each test. `auth_client` continues to yield a logged-in `TestClient`.

- [ ] **Step 1: Add session + per-test fixtures to `backend/tests/conftest.py`**

```python
import os
import pytest
from accordance.config import get_settings
from accordance import db

_ALL_TABLES = (
    "reports runs chunks findings judge_traces assessor_corrections "
    "llm_usage run_completions users sessions"
).split()


def _test_db_url() -> str:
    return os.environ.get("TEST_DATABASE_URL") or os.environ["DATABASE_URL"]


@pytest.fixture(scope="session", autouse=True)
def _pg_session():
    os.environ["DATABASE_URL"] = _test_db_url()
    get_settings.cache_clear()
    s = get_settings()
    db.init_pool(s)
    with db.connection() as conn:
        db.ensure_schema(conn)
        from accordance.indexer.embedder import embedding_dim
        db.ensure_embedding_dim(conn, dim=embedding_dim(s.embedding_model))
    yield
    db.close_pool()


@pytest.fixture(autouse=True)
def _truncate(_pg_session):
    with db.connection() as conn:
        conn.execute(
            f"TRUNCATE {', '.join(_ALL_TABLES)} RESTART IDENTITY CASCADE"
        )
    yield
```

Keep the existing `_reset_settings_cache` autouse fixture.

- [ ] **Step 2: Port `auth_client` in `backend/tests/api/conftest.py`**

Replace the SQLite-tmp_path setup with pooled inserts:

```python
@pytest.fixture
def auth_client(monkeypatch, tmp_path):
    # DATA_DIR still holds PDFs + health probe; DB is Postgres via the pool.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    from accordance.db import connection
    from accordance.users import hash_password
    with connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            ("tester", hash_password("pw")),
        )
    from accordance.main import create_app
    client = TestClient(create_app())
    client.post("/api/auth/login", json={"username": "tester", "password": "pw"})
    yield client
```

(Adjust to match the existing fixture's exact shape — keep its return type and any helpers.)

- [ ] **Step 3: Add a smoke test**

```python
# backend/tests/test_harness_smoke.py
from accordance.db import connection


def test_pool_round_trip():
    with connection() as conn:
        assert conn.execute("SELECT 1 AS one").fetchone()["one"] == 1
```

- [ ] **Step 4: Run**

Run: `pytest backend/tests/test_harness_smoke.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/conftest.py backend/tests/api/conftest.py backend/tests/test_harness_smoke.py
git commit -m "test: Postgres-backed test harness (pooled fixtures + truncate isolation)"
```

---

## Task 4: Rewrite `vector_store.py` for pgvector + PG full-text

**Files:**
- Rewrite: `backend/src/accordance/indexer/vector_store.py`
- Test: `backend/tests/indexer/test_vector_store.py` (rewrite)

**Interfaces:**
- Consumes: `db.connection()` connections (dict_row, pgvector-registered). `Embedder.embed_documents/embed_query`.
- Produces: `VectorStore(conn, embedder, mode)` with unchanged public methods: `write(run_id, chunks) -> list[int]`, `retrieve(run_id, query, k)`, `retrieve_dense`, `retrieve_bm25`, `retrieve_hybrid`, `retrieve_by_tag`, `retrieve_page_siblings`, returning `RetrievedChunk` dicts. `reciprocal_rank_fusion` unchanged. Removes `_serialize_f32`, `_db_lock`, `_build_fts_query`→replaced by `_to_tsquery`.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/indexer/test_vector_store.py  (REPLACE FILE)
import pytest
from accordance.db import connection, ensure_embedding_dim
from accordance.indexer.vector_store import VectorStore
from accordance.indexer.chunker import Chunk


class FakeEmbedder:
    """Deterministic 8-dim embeddings keyed on whether 'water' is in the text."""
    def embed_documents(self, texts):
        return [[1.0, 0, 0, 0, 0, 0, 0, 0] if "water" in t.lower()
                else [0, 1.0, 0, 0, 0, 0, 0, 0] for t in texts]
    def embed_query(self, q):
        return [1.0, 0, 0, 0, 0, 0, 0, 0] if "water" in q.lower() else [0, 1.0, 0, 0, 0, 0, 0, 0]


def _seed_run(conn, run_id):
    conn.execute("INSERT INTO reports (id, name) VALUES (%s, 'r')", (run_id + "_rep",))
    conn.execute(
        "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
        "pdf_sha256, pdf_path, status) VALUES "
        "(%s, %s, 1, 'initial', 'f', 's', 'p', 'indexing')",
        (run_id, run_id + "_rep"))


@pytest.fixture
def store():
    with connection() as conn:
        ensure_embedding_dim(conn, dim=8)
        yield VectorStore(conn, FakeEmbedder(), mode="hybrid"), conn


def test_write_and_dense_retrieve_is_run_scoped(store):
    vs, conn = store
    _seed_run(conn, "runA")
    _seed_run(conn, "runB")
    vs.write("runA", [Chunk(page=1, text="water withdrawal 303-3")])
    vs.write("runB", [Chunk(page=1, text="water withdrawal other run")])
    hits = vs.retrieve_dense("runA", "water", k=5)
    assert len(hits) == 1
    assert all(h["chunk_id"] for h in hits)  # only runA's chunk


def test_bm25_or_semantics(store):
    vs, conn = store
    _seed_run(conn, "runA")
    vs.write("runA", [Chunk(page=1, text="greenhouse gas emissions"),
                      Chunk(page=2, text="board governance")])
    hits = vs.retrieve_bm25("runA", "emissions board", k=5)
    assert len(hits) == 2  # OR: both chunks hit at least one token
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest backend/tests/indexer/test_vector_store.py -v`
Expected: FAIL (old vec0 implementation errors).

- [ ] **Step 3: Rewrite `vector_store.py`**

Key changes (full method bodies):

```python
import re
import threading  # keep ONLY if other code imports it; otherwise remove
from collections import defaultdict
from typing import Literal, TypedDict

from accordance.indexer.chunker import Chunk
from accordance.indexer.embedder import Embedder

RetrievalMode = Literal["hybrid", "dense", "bm25"]


def _to_tsquery(q: str) -> str:
    """OR-join sanitized alnum tokens into a tsquery string: 'a | b | c'.
    Returns '' when no usable tokens (caller treats as no BM25 hits)."""
    tokens = re.findall(r"\w+", q.lower())
    return " | ".join(tokens)


def reciprocal_rank_fusion(rankings, k_constant: int = 60):
    scores: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] += 1.0 / (k_constant + rank)
    return sorted(scores.items(), key=lambda x: -x[1])


class RetrievedChunk(TypedDict):
    chunk_id: int
    page: int
    text: str
    distance: float


class VectorStore:
    def __init__(self, conn, embedder: Embedder, mode: RetrievalMode = "hybrid") -> None:
        self.conn = conn
        self.embedder = embedder
        self.mode = mode
        # No _db_lock: each worker thread gets its own pooled connection, and
        # Postgres MVCC removes the sqlite-vec interleaving hazard.

    def _delete_run(self, run_id: str) -> None:
        self.conn.execute("DELETE FROM chunks WHERE run_id=%s", (run_id,))

    def write(self, run_id: str, chunks: list[Chunk]) -> list[int]:
        self._delete_run(run_id)
        texts = [c.text for c in chunks]
        vectors = self.embedder.embed_documents(texts)
        ids: list[int] = []
        # One transaction = one commit for the whole batch (autocommit otherwise
        # fsyncs per row). text_tsv is generated; embedding is a pgvector column.
        with self.conn.transaction():
            for c, v in zip(chunks, vectors, strict=True):
                row = self.conn.execute(
                    "INSERT INTO chunks (run_id, page, text, embedding) "
                    "VALUES (%s, %s, %s, %s) RETURNING id",
                    (run_id, c.page, c.text, v),
                ).fetchone()
                ids.append(row["id"])
        return ids

    def retrieve(self, run_id, query, k=5):
        if self.mode == "dense":
            return self.retrieve_dense(run_id, query, k)
        if self.mode == "bm25":
            return self.retrieve_bm25(run_id, query, k)
        return self.retrieve_hybrid(run_id, query, k)

    def retrieve_dense(self, run_id, query, k=5):
        qvec = self.embedder.embed_query(query)
        rows = self.conn.execute(
            "SELECT id, page, text, embedding <=> %s AS distance "
            "FROM chunks WHERE run_id=%s AND embedding IS NOT NULL "
            "ORDER BY embedding <=> %s LIMIT %s",
            (qvec, run_id, qvec, k),
        ).fetchall()
        return [{"chunk_id": r["id"], "page": r["page"], "text": r["text"],
                 "distance": float(r["distance"])} for r in rows]

    def retrieve_bm25(self, run_id, query, k=5):
        tsq = _to_tsquery(query)
        if not tsq:
            return []
        rows = self.conn.execute(
            "SELECT id, page, text, "
            "ts_rank_cd(text_tsv, to_tsquery('english', %s)) AS rank "
            "FROM chunks WHERE run_id=%s AND text_tsv @@ to_tsquery('english', %s) "
            "ORDER BY rank DESC LIMIT %s",
            (tsq, run_id, tsq, k),
        ).fetchall()
        # Flip sign so smaller distance = better, matching the dense convention.
        return [{"chunk_id": r["id"], "page": r["page"], "text": r["text"],
                 "distance": -float(r["rank"])} for r in rows]

    def retrieve_by_tag(self, run_id, disclosure_id, limit=5):
        pattern = re.compile(rf"GRI\s*{re.escape(disclosure_id)}(?![\d-])")
        rows = self.conn.execute(
            "SELECT id, page, text FROM chunks WHERE run_id=%s AND text LIKE '%%GRI%%' "
            "ORDER BY page", (run_id,)).fetchall()
        out = []
        for r in rows:
            if pattern.search(r["text"]):
                if len(out) >= limit:
                    break
                out.append({"chunk_id": r["id"], "page": r["page"],
                            "text": r["text"], "distance": 0.0})
        return out

    def retrieve_page_siblings(self, run_id, pages, exclude_ids, limit=50):
        if not pages:
            return []
        page_ph = ",".join("%s" for _ in pages)
        excl = (f" AND id NOT IN ({','.join('%s' for _ in exclude_ids)})"
                if exclude_ids else "")
        sql = (f"SELECT id, page, text FROM chunks WHERE run_id=%s "
               f"AND page IN ({page_ph}){excl} ORDER BY id LIMIT %s")
        params = [run_id, *pages, *exclude_ids, limit] if exclude_ids \
            else [run_id, *pages, limit]
        rows = self.conn.execute(sql, params).fetchall()
        return [{"chunk_id": r["id"], "page": r["page"], "text": r["text"],
                 "distance": 0.0} for r in rows]

    def retrieve_hybrid(self, run_id, query, k=5):
        over = max(k * 4, 20)
        dense = self.retrieve_dense(run_id, query, over)
        bm25 = self.retrieve_bm25(run_id, query, over)
        if not dense and not bm25:
            return []
        if not bm25:
            return dense[:k]
        if not dense:
            return bm25[:k]
        rankings = [[r["chunk_id"] for r in dense], [r["chunk_id"] for r in bm25]]
        fused = reciprocal_rank_fusion(rankings)
        by_id = {}
        for r in dense:
            by_id.setdefault(r["chunk_id"], r)
        for r in bm25:
            by_id.setdefault(r["chunk_id"], r)
        out = []
        for cid, _ in fused[:k]:
            if cid in by_id:
                out.append(by_id[cid])
        return out
```

Notes for the implementer:
- `%%GRI%%` — the doubled `%` escapes the literal `%` for a `LIKE` pattern in a psycopg-parameterized query (psycopg treats `%` specially).
- pgvector's `register_vector` (set on every pooled connection in Task 2) lets you pass a Python `list[float]` directly as a `vector` param — no `struct.pack`.

- [ ] **Step 4: Run tests**

Run: `pytest backend/tests/indexer/test_vector_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
ruff check backend/src/accordance/indexer/vector_store.py && ruff format backend/src/accordance/indexer/vector_store.py
git add backend/src/accordance/indexer/vector_store.py backend/tests/indexer/test_vector_store.py
git commit -m "feat(indexer): pgvector + Postgres FTS VectorStore (chunks-folded schema)"
```

---

## Task 5: Port `graph/nodes.py` — pooled judge fan-out + dialect

**Files:**
- Modify: `backend/src/accordance/graph/nodes.py`
- Test: `backend/tests/graph/test_judge_concurrency.py` (port), `backend/tests/graph/test_*` (port as needed)

**Interfaces:**
- Consumes: `db.connection()` / `db.get_pool()`.
- Produces: `judge_all_node(...)`, `aggregate_node(...)`, `index_node(...)`, `_record_completion(...)` — same signatures, Postgres-backed.

- [ ] **Step 1: Port the judge fan-out connection block (lines ~588–633)**

Replace the thread-local `db_connect(Path(db_file))` + `load_vec_extension` + `_main_db_file`/`use_per_thread`/in-memory-fallback machinery with pooled connections:

```python
from accordance.db import connection as db_connection

def _one(d):
    try:
        with db_connection() as c:
            st = VectorStore(c, store.embedder, mode=store.mode)
            return judge_one_node(state, d, st, llm, c,
                                  reranker=reranker, rerank_top_n=rerank_top_n,
                                  cache_system=cache_system, tag_aware=tag_aware,
                                  tag_limit=tag_limit)
    except Exception:
        logger.exception("judge_one_node crashed for disclosure %s", d.id)
        return {"findings": []}

with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="judge") as ex:
    for res in ex.map(_one, disclosures):
        findings.extend(res.get("findings", []))
```

Delete `_main_db_file`, the `tls`/`opened`/`opened_lock` plumbing, and the `db_connect`/`load_vec_extension` import.

- [ ] **Step 2: Apply the dialect rules across the file**

Per the inventory (graph/nodes.py: 50 `?` placeholders, lines incl. 128, 134, 187, 313, 390, 480, 505, 649, 669, 681–682, 703, 711–714, 743):
- `?` → `%s` everywhere (including any `",".join("?" ...)` → `"%s"`).
- Boolean writes: line 119 `evidence_verified` `None if ... else (1 if .. else 0)` → `t.evidence_verified` (pass the Python bool/None directly). Line 134 `rejudged` `1 if t.rejudged else 0` → `t.rejudged`. Line 505 `vision_fallback_used` `1 if vision_used else 0` → `vision_used`.
- `INSERT OR IGNORE` (lines 649, 711) → `INSERT ... ON CONFLICT DO NOTHING`. For line 711 the conflict target is `(run_id, disclosure_id)`; for 649 it is `(run_id)`. Write them explicitly:
  - `INSERT INTO run_completions (run_id, user_id) VALUES (%s, %s) ON CONFLICT (run_id) DO NOTHING`
  - `INSERT INTO findings (...) VALUES (..., 'error', ...) ON CONFLICT (run_id, disclosure_id) DO NOTHING`
- The existing `ON CONFLICT(run_id, disclosure_id) DO UPDATE SET ... = excluded.x` (lines 481–489) is already valid Postgres — keep as-is (lowercase `excluded` works).

- [ ] **Step 3: Run the graph tests**

Run: `pytest backend/tests/graph/test_judge_concurrency.py -v`
Expected: PASS (concurrent judge writes land; no "database is locked" possible).

- [ ] **Step 4: Commit**

```bash
ruff check backend/src/accordance/graph/nodes.py && ruff format backend/src/accordance/graph/nodes.py
git add backend/src/accordance/graph/nodes.py backend/tests/graph/
git commit -m "feat(graph): pooled judge fan-out + Postgres dialect in nodes.py"
```

---

## Task 6: Port `graph/build.py` + `run_graph`

**Files:**
- Modify: `backend/src/accordance/graph/build.py`
- Test: `backend/tests/graph/test_build_or_run.py` (port/create)

**Interfaces:**
- `build_graph(kb, conn, embedder, llm, ...)` keeps the `conn` parameter (the graph spine connection, borrowed by the caller). No `sqlite3` import; type hint `conn` loosely (`psycopg.Connection`).

- [ ] **Step 1:** Replace `import sqlite3` and the `conn: sqlite3.Connection` hints with `import psycopg` / `conn: psycopg.Connection`. No logic change — `index_node`/`aggregate_node` already take `conn`.

- [ ] **Step 2: Run**

Run: `pytest backend/tests/graph/test_build_or_run.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/src/accordance/graph/build.py backend/tests/graph/
git commit -m "refactor(graph): drop sqlite typing in build.py"
```

---

## Task 7: The `_open_conn` seam + app lifespan

**Files:**
- Modify: `backend/src/accordance/api/runs.py` (the `_open_conn` definition only, lines 124–129)
- Modify: `backend/src/accordance/main.py` (lifespan: `init_pool` / `close_pool`)
- Modify: `backend/src/accordance/eval/runner.py`, `backend/src/accordance/eval/bootstrap.py` (their `_open_conn` → `connect_direct`)
- Test: `backend/tests/api/test_health.py` (port/create)

**Interfaces:**
- Produces: `_open_conn(settings)` returns the `db.connection()` **context manager** (callers use `with _open_conn(settings) as conn:`). Eval/CLI keep a plain connection via `connect_direct`.

- [ ] **Step 1: Replace `_open_conn` in `api/runs.py`**

```python
from accordance.db import connection as _db_connection

def _open_conn(settings: Settings):
    # Borrow a pooled connection. Schema is ensured once at startup (lifespan),
    # not per request. Returns a context manager: `with _open_conn(s) as conn:`.
    return _db_connection()
```

- [ ] **Step 2: Wire the pool into the lifespan (`main.py`)**

At the top of `_lifespan`, before the health/reconcile block:

```python
from accordance.db import init_pool, close_pool, ensure_schema, ensure_embedding_dim
from accordance.indexer.embedder import embedding_dim

init_pool(settings)
with _open_conn(settings) as conn:
    ensure_schema(conn)
    ensure_embedding_dim(conn, dim=embedding_dim(settings.embedding_model))
```

Convert the existing startup reconcile/bootstrap + `_check_health` blocks from
`conn = _open_conn(...); try: ... finally: conn.close()` to
`with _open_conn(settings) as conn:`. After `yield` (shutdown), add `close_pool()`
**after** `drain_active_runs(...)`.

- [ ] **Step 3: Port eval `_open_conn` copies**

In `eval/runner.py` and `eval/bootstrap.py`:

```python
from accordance.db import connect_direct, ensure_schema, ensure_embedding_dim
from accordance.indexer.embedder import embedding_dim

def _open_conn(settings: Settings):
    conn = connect_direct(settings)
    ensure_schema(conn)
    ensure_embedding_dim(conn, dim=embedding_dim(settings.embedding_model))
    return conn
```

These callers keep `try/finally conn.close()` (a direct connection, not pooled).

- [ ] **Step 4: Write/port the health test**

```python
# backend/tests/api/test_health.py
def test_health_ok(auth_client):
    r = auth_client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] in ("ok", "healthy")  # match existing payload
```

- [ ] **Step 5: Run**

Run: `pytest backend/tests/api/test_health.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/accordance/api/runs.py backend/src/accordance/main.py backend/src/accordance/eval/runner.py backend/src/accordance/eval/bootstrap.py backend/tests/api/test_health.py
git commit -m "feat(api): pooled _open_conn seam + lifespan pool init/close"
```

---

## Task 8: Port `api/runs.py` SQL (placeholders, RETURNING, transactions, booleans)

**Files:**
- Modify: `backend/src/accordance/api/runs.py`
- Test: `backend/tests/api/test_runs*.py`, `backend/tests/api/test_reports.py` (run the ones exercising runs)

**Interfaces:** unchanged public endpoints.

- [ ] **Step 1: Convert all `conn = _open_conn(...)` blocks to `with _open_conn(settings) as conn:`** (33 sites total across the API; this file has the most — runs.py call sites: 243, 324, 423, 482, 549, 565, 607, 666, 688, 778). Drop the `try/finally conn.close()` wrappers (the context manager returns the connection to the pool). Keep inner `try/except HTTPException` as needed.

- [ ] **Step 2: Apply dialect rules** (inventory: 61 `?` in runs.py):
- `?` → `%s` (incl. the dynamic `",".join("?" * len(_INFLIGHT_STATUSES))` at line 146 → `"%s"`).
- `lastrowid` at line 538: replace the insert with `... RETURNING id` and read `row["id"]`:
  ```python
  new_id = conn.execute(
      "INSERT INTO assessor_corrections (...) VALUES (...) RETURNING id", (...)
  ).fetchone()["id"]
  row = conn.execute("SELECT * FROM assessor_corrections WHERE id=%s", (new_id,)).fetchone()
  ```
- Explicit transaction `delete_run` (lines 709–723): the explicit `chunk_vectors`/`chunks_fts` `executemany` deletes are **gone** (folded schema → `ON DELETE CASCADE` clears chunks). Replace the whole `BEGIN IMMEDIATE ... COMMIT` block with:
  ```python
  with conn.transaction():
      conn.execute("DELETE FROM runs WHERE id=%s", (run_id,))
  ```
  (Chunks cascade automatically. Keep any PDF-file cleanup that was alongside it.)
- `conn.commit()` no-ops at lines 536, 576: **delete them** (autocommit). If two statements must be atomic (the supersede UPDATE + INSERT in `create_correction`), wrap them in `with conn.transaction():` instead.
- Boolean SQL: line 520/574 `superseded=1` → `superseded=TRUE`; line 553/637 `superseded=0` → `superseded=FALSE`. Pydantic read line 632 `bool(fr["vision_fallback_used"])` already works on a real bool (keep).

- [ ] **Step 3: Run runs/reports API tests**

Run: `pytest backend/tests/api/test_reports.py -v` and any `backend/tests/api/test_runs*.py`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
ruff check backend/src/accordance/api/runs.py && ruff format backend/src/accordance/api/runs.py
git add backend/src/accordance/api/runs.py backend/tests/api/
git commit -m "feat(api): port runs.py to Postgres (placeholders, RETURNING, transactions, booleans)"
```

---

## Task 9: Port `api/reports.py` + `api/versioning.py`

**Files:**
- Modify: `backend/src/accordance/api/reports.py`, `backend/src/accordance/api/versioning.py`
- Test: `backend/tests/api/test_reports.py`, `backend/tests/api/test_versioning*.py`, `backend/tests/api/test_runs_selection.py`

- [ ] **Step 1: `reports.py`** — `with _open_conn(...)` conversion (sites 59, 95, 121, 194, 267); `?`→`%s` (19 occurrences); the `delete_report` `BEGIN IMMEDIATE` block (lines 150–164) → `with conn.transaction(): conn.execute("DELETE FROM reports WHERE id=%s", (report_id,))` (runs + chunks cascade); `rename_report` UPDATE stays single autocommit statement.

- [ ] **Step 2: `versioning.py`** — `with _open_conn(...)` (sites 89, 215); `?`→`%s` (37 occurrences incl. dynamic builders); `lastrowid` at line 59 → `RETURNING id`.

- [ ] **Step 3: Run**

Run: `pytest backend/tests/api/test_reports.py backend/tests/api/test_runs_selection.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
ruff check backend/src/accordance/api/reports.py backend/src/accordance/api/versioning.py
git add backend/src/accordance/api/reports.py backend/src/accordance/api/versioning.py backend/tests/api/
git commit -m "feat(api): port reports.py + versioning.py to Postgres"
```

---

## Task 10: Port remaining API + auth + users modules

**Files:**
- Modify: `api/export.py`, `api/traces.py`, `api/admin.py`, `api/auth.py`, `api/me.py`, `api/stream.py`, `auth/sessions.py`, `auth/deps.py`, `users/__init__.py`, `users/__main__.py`
- Test: `backend/tests/api/test_export*.py`, `test_traces*.py`, `tests/test_sessions.py`, `tests/users/*`, `tests/auth/*`, `tests/api/test_admin*.py`

- [ ] **Step 1: Apply across all listed files**: `with _open_conn(...)` conversion; `?`→`%s`; `users/__init__.py` `lastrowid` at line 25 → `RETURNING id`; `connect_direct` for `users/__main__.py` (CLI).
- Boolean conversions (inventory exact sites):
  - `auth/sessions.py:26` `u.is_active = 1` → `u.is_active = TRUE`.
  - `api/auth.py:44` `is_active=1` → `is_active = TRUE`.
  - `users/__init__.py`: writes `(1 if active else 0, ...)`/`(1 if is_admin else 0, ...)` → pass Python bools `(active, ...)`/`(is_admin, ...)`; hardcoded `1` in INSERT (line 80) / UPDATE (lines 86, 91) → `TRUE`.
  - `api/admin.py:109` `(1 if body.is_active else 0, user_id)` → `(body.is_active, user_id)`.
  - `bool(row[...])` reads (sessions.py:37, auth.py:85, admin.py:47–48, runs.py done) — keep; they are correct on real bools.
- `eval/runner.py` boolean SQL (`vision_fallback_used=1`, `rejudged=1`, `evidence_verified=0`, `CASE WHEN ... =1`) → `= TRUE` / `= FALSE`. (Port eval queries in Task 11.)

- [ ] **Step 2: Run**

Run: `pytest backend/tests/test_sessions.py backend/tests/api/test_admin_accounts.py -v` (and the export/traces tests by their actual names).
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
ruff check backend/src/accordance/api backend/src/accordance/auth backend/src/accordance/users
git add backend/src/accordance/api backend/src/accordance/auth backend/src/accordance/users backend/tests
git commit -m "feat(api/auth/users): port remaining modules to Postgres (placeholders + booleans)"
```

---

## Task 11: Port `eval/runner.py` + `eval/bootstrap.py` queries

**Files:**
- Modify: `backend/src/accordance/eval/runner.py`, `backend/src/accordance/eval/bootstrap.py`
- Test: `backend/tests/eval/*` if present, else a smoke import.

- [ ] **Step 1:** `?`→`%s` (runner: 19, bootstrap: 2); boolean SQL `=1`/`=0` → `=TRUE`/`=FALSE` (runner lines 91, 105, 106); the report INSERT at runner:246 leaves `created_by` NULL (eval has no user).

- [ ] **Step 2: Run** any eval tests, or `python -c "import accordance.eval.runner"` to confirm no import/SQL errors.

- [ ] **Step 3: Commit**

```bash
git add backend/src/accordance/eval
git commit -m "feat(eval): port eval SQL to Postgres dialect"
```

---

## Task 12: Timestamp + boolean wire-format verification

**Files:**
- Modify: `backend/src/accordance/models.py` (only if a timestamp field is typed `str`)
- Test: `backend/tests/api/test_timestamp_format.py` (create)

**Background (from inventory):** psycopg returns `TIMESTAMPTZ` as a `datetime` (SQLite returned strings). Response models already type these as `datetime` (RunSummary, ReportSummary, etc.), so Pydantic serializes ISO-8601. The frontend `parseServerDate` accepts both `T`/space separators and zone/no-zone, so an offset suffix is fine. The lone `str(r["created_at"])` at `api/traces.py:96` now yields `"...+00:00"` — still parseable.

- [ ] **Step 1: Write the test**

```python
# backend/tests/api/test_timestamp_format.py
import re

def test_report_created_at_is_iso_parseable(auth_client):
    # create a report via upload or the lightest path that yields one, then:
    r = auth_client.get("/api/reports")
    assert r.status_code == 200
    for rep in r.json():
        # Pydantic emits ISO-8601 with 'T'; optional offset is fine.
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", rep["created_at"])
```

- [ ] **Step 2: Run** → fix any model still typed `str` for a timestamp (none expected except the deliberate traces case). 

Run: `pytest backend/tests/api/test_timestamp_format.py -v`
Expected: PASS.

- [ ] **Step 3: Frontend check** — confirm `npm run build` still passes and visually confirm a report list renders timestamps (no `Invalid Date`).

```bash
cd frontend && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add backend/tests/api/test_timestamp_format.py backend/src/accordance/models.py
git commit -m "test(api): assert timestamp wire format stays frontend-parseable"
```

---

## Task 13: Dockerfile, CI, docs, and full-suite green

**Files:**
- Modify: `Dockerfile`, `.github/workflows/ci.yml`, `docs/DEPLOYMENT.md`, `README.md`

- [ ] **Step 1: Add a Postgres service to the backend CI job** (`.github/workflows/ci.yml`). The backend job runs `pytest -q -p no:cacheprovider --timeout=300` and now needs a live pgvector Postgres. Add to the `backend` job:

```yaml
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: gri
          POSTGRES_PASSWORD: gri
          POSTGRES_DB: gri
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U gri -d gri"
          --health-interval 10s --health-timeout 5s --health-retries 5
```

And set `TEST_DATABASE_URL: postgresql://gri:gri@localhost:5432/gri` in the test step's `env:`. Keep `--timeout=300` (the process-accumulation guard). The full suite must pass against this service.

- [ ] **Step 2:** Update `docs/DEPLOYMENT.md` + `README.md`: the app now requires Postgres; document `DATABASE_URL`, `POSTGRES_PASSWORD`, the `db` compose service, and the bootstrap command (`docker compose exec app python -m accordance.users add <name>`). Remove SQLite/`gri.db` references. `Dockerfile`: no sqlite build step exists; confirm the psycopg binary wheel installs on the slim image (add `libpq5` only if the binary wheel is unavailable for the target — usually not needed with `psycopg[binary]`).

- [ ] **Step 3: Run the DB-touching test groups targeted** (never the whole suite at once):

```bash
pytest backend/tests/test_db.py backend/tests/test_db_reconcile.py backend/tests/test_db_auth_schema.py -v
pytest backend/tests/indexer/test_vector_store.py -v
pytest backend/tests/graph/ -v
pytest backend/tests/api/test_reports.py backend/tests/api/test_health.py -v
pytest backend/tests/test_sessions.py -v
```
Expected: all PASS.

- [ ] **Step 4: End-to-end smoke** — `docker compose up --build`, confirm app waits for `db` healthy, the lifespan creates the schema, the admin bootstraps, and a login works.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .github/workflows/ci.yml docs/DEPLOYMENT.md README.md
git commit -m "ci+docs: Postgres CI service + deployment docs (compose db, DATABASE_URL, bootstrap)"
```

---

# PHASE 2 — Per-user report ownership

(Phase 1 must be merged/working first: `reports.created_by` already exists in the canonical schema from Task 2.)

## Task 14: Ownership helpers

**Files:**
- Create: `backend/src/accordance/api/ownership.py`
- Test: `backend/tests/api/test_ownership_helpers.py` (create)

**Interfaces:**
- Produces:
  - `visible_reports_clause(user) -> tuple[str, list]` — returns `("", [])` for admins, else `("AND reports.created_by = %s", [user["id"]])`.
  - `assert_report_access(conn, report_id, user) -> None` — raises `HTTPException(404)` if the report is missing or (non-admin and not owner).
  - `assert_run_access(conn, run_id, user) -> str` — resolves `run_id → report_id`, asserts access, returns `report_id`. Raises `HTTPException(404)` otherwise.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/api/test_ownership_helpers.py
import pytest
from fastapi import HTTPException
from accordance.db import connection
from accordance.api.ownership import (
    visible_reports_clause, assert_report_access, assert_run_access,
)


def _mk(conn, uid, rep, run=None):
    conn.execute("INSERT INTO reports (id, name, created_by) VALUES (%s, 'r', %s)", (rep, uid))
    if run:
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status, created_by) VALUES "
            "(%s, %s, 1, 'initial', 'f', 's', 'p', 'completed', %s)", (run, rep, uid))


def test_visible_clause_admin_vs_user():
    assert visible_reports_clause({"id": 1, "is_admin": True}) == ("", [])
    clause, params = visible_reports_clause({"id": 7, "is_admin": False})
    assert "created_by = %s" in clause and params == [7]


def test_assert_report_access_owner_ok_others_404():
    with connection() as conn:
        conn.execute("INSERT INTO users (username, password_hash) VALUES ('a', 'x')")
        owner = conn.execute("SELECT id FROM users WHERE username='a'").fetchone()["id"]
        _mk(conn, owner, "rep1")
        assert_report_access(conn, "rep1", {"id": owner, "is_admin": False})  # no raise
        with pytest.raises(HTTPException) as ei:
            assert_report_access(conn, "rep1", {"id": owner + 999, "is_admin": False})
        assert ei.value.status_code == 404
        assert_report_access(conn, "rep1", {"id": owner + 999, "is_admin": True})  # admin ok


def test_assert_run_access_maps_through_report():
    with connection() as conn:
        conn.execute("INSERT INTO users (username, password_hash) VALUES ('b', 'x')")
        owner = conn.execute("SELECT id FROM users WHERE username='b'").fetchone()["id"]
        _mk(conn, owner, "rep2", "run2")
        assert assert_run_access(conn, "run2", {"id": owner, "is_admin": False}) == "rep2"
        with pytest.raises(HTTPException):
            assert_run_access(conn, "run2", {"id": owner + 999, "is_admin": False})
```

- [ ] **Step 2: Run → fail** (`pytest backend/tests/api/test_ownership_helpers.py -v`).

- [ ] **Step 3: Implement `api/ownership.py`**

```python
from fastapi import HTTPException


def visible_reports_clause(user: dict) -> tuple[str, list]:
    """SQL fragment (and params) restricting reports to the caller, unless admin.
    Intended to be appended to a WHERE that already has a condition."""
    if user.get("is_admin"):
        return "", []
    return "AND reports.created_by = %s", [user["id"]]


def assert_report_access(conn, report_id: str, user: dict) -> None:
    row = conn.execute(
        "SELECT created_by FROM reports WHERE id=%s AND deleted_at IS NULL",
        (report_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Report not found")
    if not user.get("is_admin") and row["created_by"] != user["id"]:
        raise HTTPException(404, "Report not found")  # hide existence


def assert_run_access(conn, run_id: str, user: dict) -> str:
    row = conn.execute(
        "SELECT r.report_id, rep.created_by "
        "FROM runs r JOIN reports rep ON rep.id = r.report_id "
        "WHERE r.id=%s AND rep.deleted_at IS NULL",
        (run_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Run not found")
    if not user.get("is_admin") and row["created_by"] != user["id"]:
        raise HTTPException(404, "Run not found")
    return row["report_id"]
```

- [ ] **Step 4: Run → pass. Commit.**

```bash
git add backend/src/accordance/api/ownership.py backend/tests/api/test_ownership_helpers.py
git commit -m "feat(api): report-ownership access helpers (owner-only, admin bypass, 404)"
```

---

## Task 15: Stamp the owner at report creation

**Files:**
- Modify: `backend/src/accordance/api/runs.py` (`_persist_new_run`, INSERT at line 359)
- Test: `backend/tests/api/test_report_ownership.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_report_ownership.py
#
# Helper: there is no standalone "minimal upload" helper today. Locate the
# existing create-run test (backend/tests/api/test_runs*.py — the one that POSTs
# a PDF to /api/runs), and COPY its exact multipart request into this local
# helper, returning the new report id from the response JSON. Do not invent the
# field names — copy them from that passing test.
def _upload_minimal_report(client) -> str:
    # EXAMPLE shape — replace the body with the real request copied from the
    # existing create-run test:
    #   resp = client.post("/api/runs", files={"file": ("r.pdf", PDF_BYTES, "application/pdf")},
    #                      data={"name": "r"})
    #   return resp.json()["report_id"]
    ...


def test_uploaded_report_is_owned_by_creator(auth_client):
    # auth_client is logged in as 'tester'.
    rep_id = _upload_minimal_report(auth_client)  # returns report id
    from accordance.db import connection
    with connection() as conn:
        owner = conn.execute(
            "SELECT created_by FROM reports WHERE id=%s", (rep_id,)).fetchone()["created_by"]
        tester = conn.execute(
            "SELECT id FROM users WHERE username='tester'").fetchone()["id"]
        assert owner == tester
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — thread `user_id` into `_persist_new_run` (it already receives `user_id`) and add the column to the INSERT:

```python
conn.execute(
    "INSERT INTO reports (id, name, created_by) VALUES (%s, %s, %s)",
    (report_id, filename, user_id),
)
```

- [ ] **Step 4: Run → pass. Commit.**

```bash
git add backend/src/accordance/api/runs.py backend/tests/api/test_report_ownership.py
git commit -m "feat(api): stamp reports.created_by on upload"
```

---

## Task 16: Scope `api/reports.py` endpoints

**Files:**
- Modify: `backend/src/accordance/api/reports.py`
- Test: `backend/tests/api/test_report_ownership.py` (extend)

- [ ] **Step 1a: Add second-user + admin client fixtures to `backend/tests/api/conftest.py`**

```python
def _logged_in_client(username: str, *, is_admin: bool = False) -> TestClient:
    from accordance.db import connection
    from accordance.users import hash_password
    with connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, %s) "
            "ON CONFLICT (username) DO NOTHING",
            (username, hash_password("pw"), is_admin),
        )
    from accordance.main import create_app
    client = TestClient(create_app())
    client.post("/api/auth/login", json={"username": username, "password": "pw"})
    return client


@pytest.fixture
def second_user_client():
    return _logged_in_client("other")


@pytest.fixture
def admin_client():
    return _logged_in_client("boss", is_admin=True)
```

- [ ] **Step 1b: Write failing cross-user tests** (self-contained: seed a report+run owned by `tester` via SQL — no upload pipeline needed; `list_reports` skips report shells with no run, so seed both):

```python
def _seed_owned_report(username: str, rep_id: str) -> None:
    from accordance.db import connection
    with connection() as conn:
        uid = conn.execute("SELECT id FROM users WHERE username=%s", (username,)).fetchone()["id"]
        conn.execute("INSERT INTO reports (id, name, created_by) VALUES (%s, 'r', %s)", (rep_id, uid))
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status, created_by) VALUES "
            "(%s, %s, 1, 'initial', 'f.pdf', 's', 'p', 'completed', %s)",
            (rep_id + "_run", rep_id, uid))


def test_user_cannot_see_others_report(auth_client, second_user_client):
    _seed_owned_report("tester", "repX")
    assert any(r["id"] == "repX" for r in auth_client.get("/api/reports").json())
    assert all(r["id"] != "repX" for r in second_user_client.get("/api/reports").json())
    assert second_user_client.get("/api/reports/repX").status_code == 404
    assert second_user_client.delete("/api/reports/repX").status_code == 404


def test_admin_sees_all_reports(auth_client, admin_client):
    _seed_owned_report("tester", "repY")
    assert any(r["id"] == "repY" for r in admin_client.get("/api/reports").json())
    assert admin_client.get("/api/reports/repY").status_code == 200
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — add `user: Annotated[dict, Depends(require_user)]` to `list_reports`, `get_report`, `compare`, `rename_report`, `delete_report`. Apply scoping:
- `list_reports`: append `visible_reports_clause(user)` to the query:
  ```python
  clause, params = visible_reports_clause(user)
  reports = conn.execute(
      "SELECT id, name, created_at FROM reports "
      "WHERE deleted_at IS NULL " + clause, params).fetchall()
  ```
- `get_report`, `compare`, `rename_report`, `delete_report`: call
  `assert_report_access(conn, report_id, user)` immediately after opening the
  connection (before the existing logic).

- [ ] **Step 4: Run → pass. Commit.**

```bash
git add backend/src/accordance/api/reports.py backend/tests/api/
git commit -m "feat(api): scope reports endpoints to owner (admins see all)"
```

---

## Task 17: Scope `api/runs.py` read/act endpoints

**Files:**
- Modify: `backend/src/accordance/api/runs.py`
- Test: `backend/tests/api/test_run_ownership.py` (create)

- [ ] **Step 1: Failing tests** — second user gets 404 on another user's run for: `GET /api/runs/{id}`, `GET /api/runs/{id}/pdf`, `DELETE /api/runs/{id}`, `POST /api/runs/{id}/stop`, `GET/DELETE /api/runs/{id}/corrections`, `POST /api/runs/{id}/judge-more`, `POST /api/runs/{id}/retry`.

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — add `user: Annotated[dict, Depends(require_user)]` to the endpoints that lack it (`list_corrections`, `delete_correction`, `get_run`, `get_run_pdf`, `delete_run`, `stop_run`), and call `assert_run_access(conn, run_id, user)` right after opening the connection. `judge_more`, `create_correction`, `retry_run` already have `user` — add the same assert.

- [ ] **Step 4: Run → pass. Commit.**

```bash
git add backend/src/accordance/api/runs.py backend/tests/api/test_run_ownership.py
git commit -m "feat(api): scope run endpoints to owner via assert_run_access"
```

---

## Task 18: Scope versioning, traces, export, stream

**Files:**
- Modify: `api/versioning.py`, `api/traces.py`, `api/export.py`, `api/stream.py`
- Test: `backend/tests/api/test_ownership_misc.py` (create)

- [ ] **Step 1: Failing tests** — second user gets 404 on another user's: `POST /api/runs/{id}/fork`, `POST /api/reports/{id}/versions`, `GET /api/runs/{id}/traces`, `GET /api/runs/{id}/export/coverage`, `GET /api/reports/{id}/export/coverage`, `GET /api/runs/{id}/stream`; and `export_options`/`export_selected_coverage` only include the caller's reports/runs.

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — `assert_run_access` / `assert_report_access` at the top of each endpoint (all already have or get a `user` param). For `export_options` (lists reports) apply `visible_reports_clause`; for `export_selected_coverage` (multiple run ids) call `assert_run_access` for each requested run.

- [ ] **Step 4: Run → pass. Commit.**

```bash
git add backend/src/accordance/api backend/tests/api/test_ownership_misc.py
git commit -m "feat(api): scope versioning/traces/export/stream to owner"
```

---

## Task 19: Final integration + frontend empty-state

**Files:**
- Verify: `frontend/src/...` report list empty-state; no model changes expected.

- [ ] **Step 1:** Confirm a brand-new user (zero reports) sees an empty list, not an error. Add a frontend check or a backend test asserting `GET /api/reports` returns `[]` for a fresh user.

- [ ] **Step 2: Run the ownership + API test groups targeted:**

```bash
pytest backend/tests/api/test_ownership_helpers.py backend/tests/api/test_report_ownership.py backend/tests/api/test_run_ownership.py backend/tests/api/test_ownership_misc.py -v
pytest backend/tests/api/test_reports.py -v
```
Expected: all PASS.

- [ ] **Step 3:** `cd frontend && npm run build` → passes.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test: per-user ownership integration + empty-state check"
```

---

## Done

Run the `superpowers:finishing-a-development-branch` flow to open a PR from `feat/postgres-migration` → `main`. The PR description should note: fresh-start cutover (no data migration), Postgres now required, per-user run history, and the bootstrap command for the first admin.
