import uuid
from pathlib import Path

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


FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_report.pdf"


def test_delete_run_returns_204_and_404_afterwards(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    client = TestClient(create_app())
    _login(client)
    with FIXTURE.open("rb") as f:
        rid = client.post("/api/runs", files={"pdf": ("a.pdf", f, "application/pdf")}).json()[
            "run_id"
        ]

    r = client.delete(f"/api/runs/{rid}")
    assert r.status_code == 204
    assert client.get(f"/api/runs/{rid}").status_code == 404


def test_delete_run_cleans_chunks(tmp_path, monkeypatch):
    """ON DELETE CASCADE cleans up chunks when a run is deleted."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    client = TestClient(create_app())
    _login(client)
    with FIXTURE.open("rb") as f:
        rid = client.post("/api/runs", files={"pdf": ("a.pdf", f, "application/pdf")}).json()[
            "run_id"
        ]

    with connection() as conn:
        cid = conn.execute(
            "INSERT INTO chunks (run_id, page, text) VALUES (%s, %s, %s) RETURNING id",
            (rid, 1, "x"),
        ).fetchone()["id"]

    r = client.delete(f"/api/runs/{rid}")
    assert r.status_code == 204

    with connection() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM chunks WHERE id=%s", (cid,)).fetchone()["n"]
    assert n == 0


def test_delete_version_keeps_shared_pdf_when_referenced(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    client = TestClient(create_app())
    _login(client)
    with FIXTURE.open("rb") as f:
        body = f.read()
    j = client.post("/api/runs", files={"pdf": ("a.pdf", body, "application/pdf")}).json()
    rid = j["run_id"]

    second_id = str(uuid.uuid4())
    with connection() as conn:
        src = conn.execute("SELECT pdf_path, report_id FROM runs WHERE id=%s", (rid,)).fetchone()
        conn.execute(
            "INSERT INTO runs (id, report_id, parent_run_id, reused_from_run_id, "
            "version_number, kind, pdf_filename, pdf_sha256, pdf_path, status) "
            "VALUES (%s, %s, %s, %s, 2, 'retry', 'a.pdf', 'x', %s, 'completed')",
            (second_id, src["report_id"], rid, rid, src["pdf_path"]),
        )

    r = client.delete(f"/api/runs/{rid}")
    assert r.status_code == 204
    pdf_path = Path(src["pdf_path"])
    assert pdf_path.exists()

    r = client.delete(f"/api/runs/{second_id}")
    assert r.status_code == 204
    assert not pdf_path.exists()
