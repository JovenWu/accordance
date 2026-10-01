"""Versioning helpers and Fork/Retry-as-new-version semantics."""

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from accordance.api.versioning import _copy_chunks_to_new_run
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


def _seed_runs() -> tuple[str, str]:
    """Two runs in one report: parent has chunks, child is empty."""
    report_id = "rep_" + uuid.uuid4().hex[:24]
    parent_id = str(uuid.uuid4())
    child_id = str(uuid.uuid4())
    with connection() as conn:
        conn.execute(
            "INSERT INTO reports (id, name) VALUES (%s, %s)", (report_id, "test.pdf")
        )
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status) VALUES (%s,%s,1,'initial',%s,%s,%s,%s)",
            (parent_id, report_id, "test.pdf", "deadbeef", "/tmp/x.pdf", "completed"),
        )
        conn.execute(
            "INSERT INTO runs (id, report_id, parent_run_id, reused_from_run_id, "
            "version_number, kind, pdf_filename, pdf_sha256, pdf_path, status) "
            "VALUES (%s,%s,%s,%s,2,'retry',%s,%s,%s,%s)",
            (child_id, report_id, parent_id, parent_id, "test.pdf", "deadbeef", "/tmp/x.pdf", "queued"),
        )
        conn.execute(
            "INSERT INTO chunks (run_id, page, text) VALUES (%s, %s, %s)",
            (parent_id, 1, "chunk a"),
        )
        conn.execute(
            "INSERT INTO chunks (run_id, page, text) VALUES (%s, %s, %s)",
            (parent_id, 2, "chunk b"),
        )
    return parent_id, child_id


# ---------------------------------------------------------------------------
# Update endpoint helpers (used by later tests)
# ---------------------------------------------------------------------------


def test_copy_chunks_to_new_run() -> None:
    parent_id, child_id = _seed_runs()

    with connection() as conn:
        _copy_chunks_to_new_run(conn, source_run_id=parent_id, target_run_id=child_id)

        parent_chunks = conn.execute(
            "SELECT id, page, text FROM chunks WHERE run_id=%s ORDER BY page", (parent_id,)
        ).fetchall()
        child_chunks = conn.execute(
            "SELECT id, page, text FROM chunks WHERE run_id=%s ORDER BY page", (child_id,)
        ).fetchall()
    assert len(parent_chunks) == 2 == len(child_chunks)
    parent_ids = {r["id"] for r in parent_chunks}
    child_ids = {r["id"] for r in child_chunks}
    assert parent_ids.isdisjoint(child_ids)
    assert [r["text"] for r in parent_chunks] == [r["text"] for r in child_chunks]


# ---------------------------------------------------------------------------
# POST /api/reports/{report_id}/versions
# ---------------------------------------------------------------------------


def test_update_404_for_unknown_report(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    client = TestClient(create_app())
    _login(client)
    r = client.post(
        "/api/reports/rep_nope/versions",
        files={"pdf": ("x.pdf", b"%PDF-1.4 dummy", "application/pdf")},
    )
    assert r.status_code == 404


def test_update_rejects_identical_pdf(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    client = TestClient(create_app())
    _login(client)
    with FIXTURE.open("rb") as f:
        body = f.read()
    j = client.post(
        "/api/runs", files={"pdf": ("v1.pdf", body, "application/pdf")}
    ).json()

    r = client.post(
        f"/api/reports/{j['report_id']}/versions",
        files={"pdf": ("v2.pdf", body, "application/pdf")},
    )
    assert r.status_code == 409
    assert "identical" in r.json()["detail"].lower()


def test_update_creates_new_version_with_new_pdf(tmp_path, monkeypatch):
    """Slow: triggers the full graph pipeline on the new PDF.

    Marked here but NOT auto-deselected — when running locally on a warm
    Docling cache, takes ~10s. This is fine; pytest will skip via CLI.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    client = TestClient(create_app())
    _login(client)
    with FIXTURE.open("rb") as f:
        body_v1 = f.read()
    j = client.post(
        "/api/runs", files={"pdf": ("v1.pdf", body_v1, "application/pdf")}
    ).json()

    body_v2 = body_v1 + b"\n%appended"  # different hash
    r = client.post(
        f"/api/reports/{j['report_id']}/versions",
        files={"pdf": ("v2.pdf", body_v2, "application/pdf")},
    )
    assert r.status_code == 201
    out = r.json()
    assert out["version_number"] == 2

    detail = client.get(f"/api/reports/{j['report_id']}").json()
    assert len(detail["runs"]) == 2
    v2 = next(r for r in detail["runs"] if r["version_number"] == 2)
    assert v2["kind"] == "update"
    assert v2["reused_from_run_id"] is None
    assert v2["pdf_filename"] == "v2.pdf"
