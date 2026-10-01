# SQLite → PostgreSQL migration — design

**Date:** 2026-06-27
**Status:** Approved design (pre-plan)
**Supersedes:** the 2026-06-23 "keep SQLite" decision (revisit trigger met: locking/contention pain + data growth + PM mandate).

## 1. Context & decision

`accordance` currently runs on SQLite with two SQLite-only extensions: `sqlite-vec`
(vec0 virtual table for dense KNN) and FTS5 (`chunks_fts` for the BM25 half of
hybrid retrieval). A prior decision deliberately kept SQLite; that decision's
revisit trigger has now been met. We are moving the datastore to PostgreSQL.

Decisions locked during brainstorming:

- **Driver / strategy:** faithful raw-SQL port (Approach A). `psycopg` v3 +
  `psycopg_pool`, keeping the existing raw-SQL style. **No** SQLAlchemy/Alembic.
- **Vectors:** `pgvector`. **Lexical:** native Postgres full-text search
  (`tsvector`/`ts_rank_cd`). **No** ParadeDB `pg_search` (fallback only if an
  eval proves native FTS regresses retrieval — RRF consumes rank order only, and
  the eval record says retrieval is not the accuracy lever).
- **Data:** **start fresh** — no ETL. Existing reports/runs/findings/chunks/users
  are abandoned. The admin account re-bootstraps from `.env` on first boot.
- **Topology:** **single app instance** (unchanged). In-process thread-per-run
  worker and local-disk PDFs are retained. No job queue / object storage.
- **Hosting:** **self-hosted Postgres as a Docker Compose service**
  (`pgvector/pgvector` image). App connects via `DATABASE_URL`, so a managed
  instance later is a config change, not a code change.
- **Chunk schema:** **fold** embedding + full-text into the `chunks` table
  (3 tables → 1).
- **Flag columns:** **convert to real `BOOLEAN`** (idiomatic PG).
- **Pool sizing:** **auto-derive** a deadlock-safe `max_size` from the existing
  concurrency knobs.
- **Per-user ownership (folded in):** run history becomes **per-user** instead of
  universal. Reports are owned by their creator; only the owner can see/act on a
  report and its versions. **Admins see all** (owner filter bypassed when
  `is_admin`). No cross-user sharing. Cross-user access returns **404** (hide
  existence), not 403. See §12.

## 2. Goals / non-goals

**Goals**

- All persistence on PostgreSQL; the "database is locked" failure class is gone.
- Dense + lexical hybrid retrieval preserved (same RRF fusion, same public
  `VectorStore` behavior).
- Single, env-driven configuration (`DATABASE_URL`); `docker compose up` brings
  up app + Postgres self-contained.
- **Run history is per-user:** each user sees and acts on only their own reports
  (admins see all). No data leakage across accounts.
- Test suite runs green against a real Postgres.

**Non-goals (YAGNI)**

- Multi-instance / horizontal scaling, job queue, externalized PDF storage.
- SQLAlchemy / Alembic.
- ParadeDB / literal BM25.
- Migrating existing SQLite data.
- Converting JSON-in-TEXT columns (`elements_json`, `queries_json`, …) to JSONB
  (code does manual `json.loads/dumps`; leave as `TEXT`).
- **Cross-user sharing** of reports (owner + admin only); per-run (vs per-report)
  ownership; sharing UI/tables. Owner-only is the model.

## 3. Architecture

Unchanged: one FastAPI container serving API + SPA; a daemon thread per run
executing the LangGraph pipeline (extract → index → judge → aggregate); PDFs on
the `./data` bind-mount.

Changed: a process-wide `psycopg_pool.ConnectionPool` owns all DB connections.
The `_open_conn(settings)` seam remains the single entry point but now lends a
pooled connection (context-managed) instead of opening a SQLite file. Schema
creation runs **once at startup**, not per request.

```
FastAPI app ── _open_conn() → db.connection() ──┐
run worker thread ── db.connection() (spine) ───┼──→ psycopg_pool ──→ Postgres
judge fan-out ── db.connection() per worker ────┘                    (pgvector)
```

## 4. Schema (canonical, fresh DB)

`ensure_schema(conn)` runs one idempotent DDL block at startup, gated by
`app_meta.schema_version`. Highlights (full DDL authored in implementation):

- `CREATE EXTENSION IF NOT EXISTS vector;`
- **`chunks` absorbs vectors + full-text** (was `chunks` + `chunk_vectors` +
  `chunks_fts`):

  ```sql
  CREATE TABLE IF NOT EXISTS chunks (
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id    TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    page      INTEGER NOT NULL,
    text      TEXT NOT NULL,
    embedding vector(<dim>),
    text_tsv  tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
  );
  CREATE INDEX IF NOT EXISTS chunks_run_id_idx ON chunks(run_id);
  CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);
  CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING gin (text_tsv);
  ```

- **`reports` gains an owner:** add
  `created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL` (mirrors
  `runs.created_by`; `SET NULL` so deleting a user orphans their reports to
  admin-only visibility rather than cascading them away) plus
  `CREATE INDEX reports_created_by_idx ON reports(created_by)`. See §12.
- All other tables port near-verbatim. Type mapping:
  - **Surrogate PKs → `GENERATED ALWAYS AS IDENTITY`.** Keep **`users.id` as
    `INTEGER` IDENTITY** so the existing `INTEGER` user-FK columns
    (`reports.created_by`, `runs.created_by`, `sessions.user_id`,
    `llm_usage.user_id`, `run_completions.user_id`) need **no type change** (an
    FK column must match its referenced PK type). High-volume PKs
    (`chunks.id`, `findings.id`, `judge_traces.id`, `assessor_corrections.id`,
    `llm_usage.id`, `run_completions.id`) → `BIGINT` IDENTITY.
  - **Flag columns → `BOOLEAN`:** `users.is_active` (DEFAULT TRUE),
    `users.is_admin` (DEFAULT FALSE), `findings.vision_fallback_used`
    (DEFAULT FALSE), `judge_traces.rejudged` (DEFAULT FALSE),
    `judge_traces.evidence_verified` (NULL), `assessor_corrections.superseded`
    (DEFAULT FALSE). **Not flags — stay INTEGER:** `findings.score` (0–5),
    `judge_traces.attempt`, token counts.
  - `sessions.expires_at` (epoch seconds) → `BIGINT`.
  - Timestamps → `TIMESTAMPTZ DEFAULT now()` (store UTC). **See §9 hazard:**
    psycopg returns these as `datetime`, not `str`.
  - JSON-bearing `*_json` columns stay `TEXT`.
  - CHECK constraints, FKs, `ON DELETE CASCADE`/`SET NULL` carry over directly
    (Postgres always enforces FKs; no `PRAGMA foreign_keys`).

- **Dim-change self-heal** (replaces `ensure_vec_schema`): keep
  `app_meta.embedding_dim`. On a dim change, within a transaction:
  `DELETE FROM chunks; DELETE FROM findings; DELETE FROM judge_traces;`
  then `ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(<newdim>);`
  recreate the HNSW index, and mark completed/failed runs `failed` with the same
  "click Retry" message as today.

## 5. Retrieval (pgvector + PG-FTS)

`VectorStore`'s public surface is unchanged; internals rewritten:

- **Dense** (`retrieve_dense`):
  ```sql
  SELECT id, page, text, embedding <=> %s AS distance
  FROM chunks WHERE run_id = %s
  ORDER BY embedding <=> %s LIMIT %s
  ```
  Cosine (`<=>`); for unit-norm OpenAI embeddings this ranks identically to the
  old L2 vec0. The vec0 partition key becomes a `WHERE run_id` filter.
- **Lexical** (`retrieve_bm25`): build an OR `tsquery` from sanitized tokens
  (preserving `_build_fts_query`'s OR-join), then
  `WHERE run_id = %s AND text_tsv @@ %s ORDER BY ts_rank_cd(text_tsv, %s) DESC LIMIT %s`.
  Expose `-ts_rank_cd` as `distance` (lower = better, matching the dense sign).
- `reciprocal_rank_fusion`, `retrieve_hybrid`, `retrieve_by_tag`,
  `retrieve_page_siblings` — **logic unchanged** (RRF uses ranks; tag/sibling are
  plain SQL, `?`→`%s`).
- **Delete** `_serialize_f32` (pgvector adapts Python lists via
  `register_vector`) and `_db_lock` + the sqlite-vec interleaving guard (separate
  pooled connections + MVCC remove that hazard). `write()` uses
  `INSERT … RETURNING id`; `_delete_run` collapses to
  `DELETE FROM chunks WHERE run_id = %s`.

## 6. Connection pool & worker fan-out

`db.py` gains:

- `init_pool(settings)` — build the `ConnectionPool` at startup; `configure=`
  hook per connection sets `row_factory=dict_row`, `register_vector(conn)`, and
  `autocommit=True` (preserves today's autocommit semantics; the lone explicit
  transaction in `reports.py` uses `with conn.transaction():`).
- `connection()` — context manager that borrows from the pool and returns it.
- `connect_direct(settings)` — a non-pooled connection for CLI/eval entrypoints
  (`eval/runner.py`, `eval/bootstrap.py`, `users/__main__.py`).
- `ensure_schema(conn)` / `ensure_embedding_dim(conn, dim)` — startup-only.

`_open_conn(settings)` returns `db.connection()`. Call sites change from
`conn = _open_conn(...); try: … finally: conn.close()` to
`with _open_conn(...) as conn:` (~40 sites, mechanical). Schema-ensure is removed
from this path.

Judge fan-out (`judge_all_node`): delete `_main_db_file`, `use_per_thread`, the
thread-local `db_connect(file)` + `load_vec_extension`, and the in-memory
fallback. Each worker does `with pool.connection() as c:` for its disclosures.

**Deadlock-safe pool sizing:** an admitted run holds 1 spine connection + up to
`judge_concurrency` worker connections; admission is capped at
`max_concurrent_runs`. Set
`max_size = max_concurrent_runs × (1 + judge_concurrency) + api_headroom`
(defaults: 4 × (1 + 3) + 8 = 24) so every admitted run can always acquire all of
its connections. Expose `DB_POOL_MIN_SIZE` / `DB_POOL_MAX_SIZE` (max overrides
the derived value). Verify Postgres `max_connections` (default 100) comfortably
exceeds `max_size`.

## 7. Migrations

Fresh start ⇒ the SQLite v1→v7 history is irrelevant and is **deleted**:
`_migrate_v1_to_v2`, `_apply_pre_schema_migrations`,
`_apply_post_schema_migrations`, and all `PRAGMA table_info` / `sqlite_master`
logic. `ensure_schema` becomes a single canonical idempotent PG DDL run once at
startup, gated by `app_meta.schema_version` (bump back to `"1"` for the new
lineage). Future schema changes = additive idempotent DDL; Alembic deferred.

## 8. Dependencies, dialect, docker, config

- **Deps (`pyproject.toml`):** add `psycopg[binary]`, `psycopg_pool`, `pgvector`;
  **remove** `sqlite-vec` and `langgraph-checkpoint-sqlite` (the checkpointer is
  unused — `g.compile()` takes no saver and nothing imports
  `langgraph.checkpoint`).
- **Dialect edits (mechanical, test-guarded):**
  - `?` → `%s` placeholders (all parameterized SQL, ~16 files).
  - `cur.lastrowid` → `INSERT … RETURNING id` (4 sites: `vector_store.write`,
    `api/runs.py:538`, `api/versioning.py:59`, `users/__init__.py:25`).
  - `INSERT OR IGNORE` → `INSERT … ON CONFLICT DO NOTHING` (2 sites in
    `graph/nodes.py`).
  - `conn.executescript(SCHEMA_SQL)` → `conn.execute(SCHEMA_SQL)` (no params).
  - `ON CONFLICT(k) DO UPDATE SET v = excluded.v` → `EXCLUDED.v`.
  - Boolean inserts/compares: `1/0` → `True/False`, `= 1` → `IS TRUE` (or pass a
    bool param); `bool(row[col])` becomes a no-op on a real bool but stays
    correct.
- **docker-compose.yml:** add
  `db: image: pgvector/pgvector:pg16`, `POSTGRES_USER/PASSWORD/DB`, named volume
  `pgdata`, `healthcheck: pg_isready`. App gains
  `depends_on: { db: { condition: service_healthy } }` and
  `DATABASE_URL=postgresql://…@db:5432/gri`. The `gri.db` bind-mount is removed;
  `./data` remains (PDFs + health probe). `.env.example` gains `DATABASE_URL` and
  `POSTGRES_*`.
- **Dockerfile:** ensure `libpq`/psycopg binary wheel works on the Linux target;
  drop any sqlite-vec build steps.
- **config.py:** add `database_url: str`; remove `db_path`; keep `data_dir` /
  `pdf_dir`. `check_required_keys` validates `DATABASE_URL` is set.
  `resolve_pdf_path` unchanged.

## 9. Known hazards (verify during implementation)

1. **Timestamps return as `datetime`, not `str`.** SQLite returned TIMESTAMP
   columns as strings; psycopg returns `datetime`. Audit every response model /
   serializer that reads a timestamp column (`created_at`, `uploaded_at`,
   `completed_at`, `expires_at` is BIGINT so unaffected). Preferred fix: type the
   response models as `datetime` and let FastAPI emit ISO-8601; **verify the
   frontend `src/lib/datetime.ts` parser accepts the emitted format** (add a test
   if needed).
2. **Boolean round-trip.** After conversion, `row["is_active"]` is a Python
   `bool`. Grep each flag column name and confirm no code relies on `int`
   identity (`is 1`, arithmetic, JSON-int serialization).
3. **`conn.execute(...).fetchone()` shortcut.** Supported by psycopg3
   `Connection.execute`; confirm no reliance on `sqlite3.Row` index access
   (`row[0]`) that `dict_row` doesn't provide — switch those to column names.
4. **Autocommit + explicit transactions.** Confirm the single explicit
   transaction (`api/reports.py` delete path) is wrapped in
   `with conn.transaction():` under `autocommit=True`.
5. **`max_connections`.** Ensure the compose Postgres allows ≥ `max_size`.

## 10. Testing

- Tests target a real Postgres via `TEST_DATABASE_URL` (default: the compose PG).
  A session fixture provisions a throwaway database/schema; a per-test fixture
  truncates (or wraps each test in a rolled-back transaction) for isolation.
- **Delete** SQLite-migration tests: `tests/test_db_migration.py`,
  `tests/db/test_migration_corrections.py`, and the vec0/FTS5 internals in
  `tests/test_db_vec.py` / `tests/indexer/test_vector_store.py`.
- **Add/rewrite:** schema-ensure idempotency; pgvector round-trip + run-scoped
  KNN (one run's vectors never leak into another's top-k); FTS OR-query + RRF
  hybrid ordering; dim-change self-heal (clears chunks, marks runs failed);
  pool checkout/return + deadlock-free fan-out; a concurrency test that previously
  reproduced "database is locked" now passes.
- **Per-user ownership (§12):** user A cannot list/get/delete/rename/compare/
  retry/fork/export/stream/trace user B's report — each returns 404 (or is
  absent from the list); an admin sees and can act on both users' reports; a new
  user with zero reports gets an empty list, not an error; `reports.created_by`
  is set on upload.
- Constraints from project memory: full `pytest` hangs locally (run targeted
  files); there is no CI. PG-backed tests need a running Postgres — flag that CI
  with a Postgres service is the right follow-up (out of scope here).

## 11. File-by-file impact (for the plan)

- `db.py` — **largest rewrite.** Pool, `connection()`, `connect_direct()`,
  canonical PG DDL, dim self-heal; delete all SQLite migration code +
  `load_vec_extension`.
- `indexer/vector_store.py` — rewrite dense/bm25/write/delete for pgvector +
  PG-FTS; drop `_serialize_f32`, `_db_lock`.
- `graph/nodes.py` — judge fan-out uses pooled connections; `?`→`%s`;
  `INSERT OR IGNORE`→`ON CONFLICT`; boolean writes.
- `graph/build.py`, `eval/runner.py`, `eval/bootstrap.py`,
  `users/__init__.py`, `users/__main__.py`, `auth/sessions.py`, `auth/deps.py`,
  `api/*.py` (runs, reports, versioning, admin, auth, me, traces, export) —
  `_open_conn` context-manager usage, `?`→`%s`, `lastrowid`→`RETURNING`, boolean
  + timestamp handling.
- **Ownership scoping (§12):** new `api/ownership.py` (or helpers in
  `api/runs.py`) with `visible_reports_filter` / `assert_report_access` /
  `assert_run_access`; inject `Depends(require_user)` + apply scoping in
  `api/reports.py`, `api/runs.py` (reads), `api/versioning.py`, `api/traces.py`,
  `api/export.py`, `api/stream.py`; stamp `reports.created_by` at the upload site.
- `main.py` — `init_pool` at startup; lifespan reconcile/bootstrap via pooled
  connection; pool close on shutdown.
- `config.py` — `database_url`, pool-size knobs; drop `db_path`.
- `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `.env.example`,
  `docs/DEPLOYMENT.md`, `README.md` — deps, services, docs.

## 12. Per-user ownership scoping (folded into this migration)

Today reports/runs are universal: every authenticated user sees every report.
We make run history **per-user**, owned at the **report** level, with **admins
seeing all**. Starting fresh means we add the owner column directly to the
canonical schema (no backfill).

**Data model**

- `reports.created_by` (added in §4) is the owner. Stamped once, at the single
  report-creation site (`api/runs.py` upload handler, which already has `user`).
  All versions (retry/fork/update) live under that report, so the report owner
  transitively owns every run; `runs.created_by` stays as-is (records who
  triggered each version, for usage attribution).
- Eval/CLI-created reports (`eval/runner.py`) have `created_by = NULL` → visible
  to admins only. Acceptable (offline tooling).

**Enforcement**

- Add two helpers in a shared place (e.g. `api/runs.py` or a small
  `api/ownership.py`):
  - `visible_reports_filter(user)` → returns a SQL fragment + params:
    `""`/no-op when `user["is_admin"]`, else `AND (created_by = %s)`.
  - `assert_report_access(conn, report_id, user)` and
    `assert_run_access(conn, run_id, user)` → resolve the owning report and raise
    **`HTTPException(404)`** when the user is not the owner and not an admin
    (404, not 403, so a report's existence isn't revealed). `assert_run_access`
    maps `run_id → report_id → reports.created_by`.
- Inject `user: dict = Depends(require_user)` into the read/act handlers that
  currently lack it, and apply the filter/assert:
  - `api/reports.py`: `list_reports` (filter), `get_report`,
    `delete_report`, `rename` (assert), `compare` (assert on the report).
  - `api/runs.py`: every run read/poll/status/cancel endpoint (assert via
    `run_id`); the run-quota count already keys on `created_by`.
  - `api/versioning.py`: retry/fork/update must `assert_report_access` on the
    target report before creating a new version.
  - `api/traces.py`, `api/export.py` (run + report routers), `stream_router`
    (SSE run status): assert via `run_id`/`report_id`.
  - **Not scoped:** `api/me.py` (self), `kb_router` (shared GRI reference data),
    `admin_router` (admin-only already).

**Frontend**

- No model change needed — the API simply returns fewer rows. Verify the report
  list/empty-state still render when a new user has zero reports. The header
  usage stats are already per-user.

**Edge cases**

- Owner account disabled (`is_active = FALSE`): they can't log in, so their
  reports are simply inaccessible until re-enabled; admins still see them.
- Owner account deleted: `ON DELETE SET NULL` → reports become admin-only
  (orphaned), not deleted.

## 13. Rollback

The work lands on a feature branch; `main` stays on SQLite until merge. Because
we start fresh (no data migration), rollback is reverting the branch — no data
reconciliation. The pre-cutover SQLite `data/gri.db` is left untouched on disk.
