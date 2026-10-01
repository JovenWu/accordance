"""Compare endpoint: side-by-side diff between two runs in one report."""

import uuid

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


def _seed_two_versions_with_findings() -> tuple[str, str, str]:
    """Return (report_id, run_a_id, run_b_id) with fabricated findings."""
    report_id = "rep_" + uuid.uuid4().hex[:24]
    a = str(uuid.uuid4())
    b = str(uuid.uuid4())
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
            (report_id, "x.pdf", tester_id),
        )
        for run_id, ver, kind, parent in [(a, 1, "initial", None), (b, 2, "retry", a)]:
            conn.execute(
                "INSERT INTO runs (id, report_id, parent_run_id, reused_from_run_id, "
                "version_number, kind, pdf_filename, pdf_sha256, pdf_path, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    run_id,
                    report_id,
                    parent,
                    parent,
                    ver,
                    kind,
                    "x.pdf",
                    "abc",
                    "/tmp/x.pdf",
                    "completed",
                ),
            )

        def add_finding(run_id, did, status, note):
            conn.execute(
                "INSERT INTO findings (run_id, disclosure_id, standard, status, note, "
                "elements_json, suggested_fix) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (run_id, did, "GRI 2", status, note, "[]", "n/a"),
            )

        add_finding(a, "GRI 305-1", "missing", "no evidence")
        add_finding(a, "GRI 305-2", "partial", "missing element 3")
        add_finding(a, "GRI 2-1", "covered", "ok")
        add_finding(b, "GRI 305-1", "covered", "scope 1 on p.42")
        add_finding(b, "GRI 305-2", "partial", "still missing element 3, clarified")
        add_finding(b, "GRI 2-1", "covered", "ok")
    return report_id, a, b


def test_compare_classifies_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    report_id, a, b = _seed_two_versions_with_findings()
    client = TestClient(create_app())
    _login(client)

    r = client.get(f"/api/reports/{report_id}/compare", params={"a": a, "b": b})
    assert r.status_code == 200
    body = r.json()
    assert body["a"]["run_id"] == a
    assert body["b"]["run_id"] == b

    by_did = {d["disclosure_id"]: d for d in body["diff"]}
    assert by_did["GRI 305-1"]["change"] == "status_changed"
    assert by_did["GRI 305-2"]["change"] == "note_changed"
    assert by_did["GRI 2-1"]["change"] == "unchanged"

    assert body["summary_delta"]["covered"]["delta"] == 1
    assert body["summary_delta"]["missing"]["delta"] == -1


def test_compare_rejects_runs_from_different_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

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
            ("r1", "a.pdf", tester_id),
        )
        conn.execute(
            "INSERT INTO reports (id, name, created_by) VALUES (%s, %s, %s)",
            ("r2", "b.pdf", tester_id),
        )
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status) VALUES (%s,%s,1,'initial','a','x','/tmp/a','completed')",
            ("run-a", "r1"),
        )
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status) VALUES (%s,%s,1,'initial','b','y','/tmp/b','completed')",
            ("run-b", "r2"),
        )

    client = TestClient(create_app())
    _login(client)
    r = client.get("/api/reports/r1/compare", params={"a": "run-a", "b": "run-b"})
    assert r.status_code == 400
