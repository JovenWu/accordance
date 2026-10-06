import pytest
from fastapi.testclient import TestClient

from accordance.auth.passwords import hash_password
from accordance.config import get_settings


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    """A TestClient already logged in as a seeded 'tester' user.

    Use in api tests that hit gated routes. Sets fake models + DATA_DIR so the
    test environment is isolated under tmp_path.

    NOTE: ``create_app`` is imported lazily (inside the function body) to keep
    import-time side-effects (pool init, lifespan) confined to test scope.
    Once all modules have been ported this can be simplified to a top-level import.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    get_settings.cache_clear()

    from accordance.db import connection

    with connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            ("tester", hash_password("pw")),
        )

    from accordance.main import create_app

    client = TestClient(create_app())
    client.post("/api/auth/login", json={"username": "tester", "password": "pw"})
    yield client


def _logged_in_client(username: str, *, is_admin: bool = False) -> TestClient:
    from accordance.db import connection
    from accordance.users import hash_password as _hash_password

    with connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, %s) "
            "ON CONFLICT (username) DO NOTHING",
            (username, _hash_password("pw"), is_admin),
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
