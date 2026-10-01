"""Root test fixtures shared across the whole suite.

``get_settings()`` is process-memoized (``lru_cache``) so production reads
``.env`` once instead of on every request. Tests, however, set a unique
``DATA_DIR`` (and fake model env) per test via ``monkeypatch``, so a leaked
cache entry would make every test reuse the first test's settings/DB. Clear
the cache around each test to keep them isolated.
"""

import os

import pytest

from accordance import db
from accordance.config import get_settings

# All tables that need truncation between tests (app_meta excluded — it holds
# schema/dim metadata that must survive across tests).
_ALL_TABLES = (
    "reports runs chunks findings judge_traces assessor_corrections "
    "llm_usage run_completions users sessions"
).split()


def _test_db_url() -> str:
    """Prefer TEST_DATABASE_URL so the suite never clobbers the dev database."""
    return os.environ.get("TEST_DATABASE_URL") or os.environ["DATABASE_URL"]


@pytest.fixture(scope="session", autouse=True)
def _pg_session():
    """One-time pool init + schema/dim bootstrap for the whole test session."""
    os.environ["DATABASE_URL"] = _test_db_url()
    # Default to fake embedder so tests never make real embedding API calls and
    # the DB column dim=8 matches FakeEmbedder(dim=8) throughout the suite.
    # Override by setting EMBEDDING_MODEL before running pytest.
    os.environ.setdefault("EMBEDDING_MODEL", "fake:fake")
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
    """Wipe all data-rows before each test for full isolation.

    Lifespan tests (test_startup_*) spin up create_app() as a TestClient context,
    which triggers pool close_pool() on exit. Re-init here so subsequent tests are
    not stranded without a pool.
    """
    try:
        db.get_pool()
    except RuntimeError:
        # Pool was closed by a lifespan test — reinitialize.
        db.init_pool(get_settings())
        # Clear the cache so the reinit's env snapshot doesn't leak into the
        # next test's monkeypatched settings.
        get_settings.cache_clear()
    with db.connection() as conn:
        conn.execute(f"TRUNCATE {', '.join(_ALL_TABLES)} RESTART IDENTITY CASCADE")
    yield


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    get_settings.cache_clear()
    # The login throttle keeps in-memory per-IP/username failure counts; all
    # TestClients share the "testclient" IP, so clear it between tests to avoid
    # one test's failed logins locking out another's.
    try:
        from accordance.api.limits import login_limiter

        login_limiter.clear()
    except Exception:
        pass
    yield
    # Join any background run-worker threads BEFORE clearing the cache. A
    # full-run test spawns a daemon thread that calls get_settings() inside
    # run_graph; if it outlives the test it would repopulate the (now cached)
    # settings with this test's reverted env and point the next test at the
    # wrong DB. Draining first makes the cache reset deterministic.
    try:
        from accordance.api.runs import drain_active_runs
    except ImportError:
        pass
    else:
        drain_active_runs(timeout=15)
    get_settings.cache_clear()
