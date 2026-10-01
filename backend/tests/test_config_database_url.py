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
    # 4 spines + 3 globally-capped judge workers + 8 headroom = 15.
    # Was 4 * (1 + 3) + 8 = 24 while workers took a connection BEFORE waiting
    # on the judge semaphore; they now wait first, so the terms add.
    assert s.effective_pool_max_size == 15


def test_db_path_attribute_removed():
    assert not hasattr(Settings(), "db_path")
