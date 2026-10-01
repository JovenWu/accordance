from fastapi.testclient import TestClient

from accordance.auth.passwords import hash_password
from accordance.db import connection
from accordance.main import create_app


def _login(client):
    with connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            ("tester", hash_password("pw")),
        )
    client.post("/api/auth/login", json={"username": "tester", "password": "pw"})


def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")


def _seed():
    with connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            ("tester", hash_password("pw")),
        )
        tester_id = conn.execute("SELECT id FROM users WHERE username=%s", ("tester",)).fetchone()[
            "id"
        ]
        conn.execute(
            "INSERT INTO reports (id, name, created_by) VALUES (%s, %s, %s)",
            ("rep1", "old.pdf", tester_id),
        )
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status) VALUES "
            "(%s, %s, 1, 'initial', 'old.pdf', 'sha', 'old.pdf', 'completed')",
            ("r1", "rep1"),
        )


def test_rename_report_updates_name(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _seed()
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")  # ensure schema
    r = client.patch("/api/reports/rep1", json={"name": "PT Vale 2024"})
    assert r.status_code == 200
    assert r.json()["name"] == "PT Vale 2024"
    # Persisted: report detail reflects the new name.
    assert client.get("/api/reports/rep1").json()["name"] == "PT Vale 2024"


def test_rename_trims_whitespace(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _seed()
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")
    r = client.patch("/api/reports/rep1", json={"name": "  Spaced Name  "})
    assert r.status_code == 200
    assert r.json()["name"] == "Spaced Name"


def test_rename_missing_report_is_404(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _seed()
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")
    assert client.patch("/api/reports/nope", json={"name": "x"}).status_code == 404


def test_rename_soft_deleted_report_is_404(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _seed()
    with connection() as conn:
        conn.execute("UPDATE reports SET deleted_at=CURRENT_TIMESTAMP WHERE id=%s", ("rep1",))
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")
    # The deleted_at IS NULL guard excludes soft-deleted reports.
    assert client.patch("/api/reports/rep1", json={"name": "x"}).status_code == 404


def test_rename_empty_name_is_422(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    _seed()
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")
    # Empty string fails the Field(min_length=1) validator.
    assert client.patch("/api/reports/rep1", json={"name": ""}).status_code == 422
    # Whitespace-only is non-empty to Pydantic but empty after strip -> handler 422.
    assert client.patch("/api/reports/rep1", json={"name": "   "}).status_code == 422
