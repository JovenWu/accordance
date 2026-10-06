from pathlib import Path

from fastapi.testclient import TestClient

from accordance.auth.passwords import hash_password
from accordance.db import connection
from accordance.main import create_app


def _login(client):
    """Seed a tester user and log in. Call after DATA_DIR is set and client is created."""
    with connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            ("tester", hash_password("pw")),
        )
    client.post("/api/auth/login", json={"username": "tester", "password": "pw"})

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_report.pdf"


def _upload(client, name="a.pdf"):
    with FIXTURE.open("rb") as f:
        return client.post(
            "/api/runs", files={"pdf": (name, f, "application/pdf")}
        ).json()


def test_list_reports_returns_one_per_upload(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    client = TestClient(create_app())
    _login(client)
    _upload(client, name="first.pdf")

    r = client.get("/api/reports")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    items = body["items"]
    assert len(items) == 1
    assert items[0]["name"] == "first.pdf"
    assert items[0]["version_count"] == 1
    assert items[0]["latest"]["version_number"] == 1
    assert items[0]["latest"]["kind"] == "initial"


def test_get_report_returns_versions_list(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    client = TestClient(create_app())
    _login(client)
    j = _upload(client, name="x.pdf")

    r = client.get(f"/api/reports/{j['report_id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == j["report_id"]
    assert body["name"] == "x.pdf"
    assert len(body["runs"]) == 1
    run = body["runs"][0]
    assert run["run_id"] == j["run_id"]
    assert run["version_number"] == 1
    assert run["kind"] == "initial"


def test_get_report_404(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    client = TestClient(create_app())
    _login(client)
    assert client.get("/api/reports/rep_nope").status_code == 404


def test_delete_report_cleans_up_chunks(tmp_path, monkeypatch):
    """Delete cascades: report DELETE removes runs and their chunks via FK CASCADE."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    client = TestClient(create_app())
    _login(client)
    j = _upload(client, name="cleanup.pdf")

    with connection() as conn:
        conn.execute(
            "INSERT INTO chunks (run_id, page, text) VALUES (%s, %s, %s)",
            (j["run_id"], 1, "synthetic chunk"),
        )
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE run_id=%s", (j["run_id"],)
        ).fetchone()
        assert row["n"] >= 1

    r = client.delete(f"/api/reports/{j['report_id']}")
    assert r.status_code == 204

    with connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE run_id=%s", (j["run_id"],)
        ).fetchone()["n"] == 0
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM reports WHERE id=%s", (j["report_id"],)
        ).fetchone()["n"] == 0


def test_delete_report_with_many_chunks_and_double_delete(tmp_path, monkeypatch):
    """The bulk delete removes every chunk and the report; a second delete is a
    clean 404 (not a crash or lock)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")

    client = TestClient(create_app())
    _login(client)
    j = _upload(client, name="many.pdf")

    with connection() as conn:
        for i in range(6):
            conn.execute(
                "INSERT INTO chunks (run_id, page, text) VALUES (%s, %s, %s)",
                (j["run_id"], 1, f"chunk {i}"),
            )

    assert client.delete(f"/api/reports/{j['report_id']}").status_code == 204

    with connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE run_id=%s", (j["run_id"],)
        ).fetchone()["n"] == 0
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM reports WHERE id=%s", (j["report_id"],)
        ).fetchone()["n"] == 0

    assert client.delete(f"/api/reports/{j['report_id']}").status_code == 404


from accordance.api.reports import _row_to_finding_view


def _base_row(**over):
    row = {
        "disclosure_id": "2-1",
        "standard": "GRI 2",
        "status": "covered",
        "score": None,
        "na_reason": None,
        "note": "n",
        "evidence_excerpt": None,
        "evidence_page": None,
        "elements_json": "[]",
        "suggested_fix": "f",
        "vision_fallback_used": 0,
    }
    row.update(over)
    return row


def test_finding_view_backmaps_legacy_status_to_score():
    assert _row_to_finding_view(_base_row(status="covered", score=None)).score == 5
    assert _row_to_finding_view(_base_row(status="partial", score=None)).score == 3
    assert _row_to_finding_view(_base_row(status="missing", score=None)).score == 1


def test_finding_view_prefers_explicit_score():
    fv = _row_to_finding_view(_base_row(status="covered", score=0, na_reason="out of scope"))
    assert fv.score == 0
    assert fv.na_reason == "out of scope"


def test_finding_view_error_status_has_no_score():
    assert _row_to_finding_view(_base_row(status="error", score=None)).score is None


def _seed_reports(names, owner="tester"):
    """Insert reports + one run each directly, with distinct uploaded_at.

    Ordering is by the LATEST run's uploaded_at, so the timestamps have to
    differ or the page boundaries are not deterministic.
    """
    with connection() as conn:
        uid = conn.execute(
            "SELECT id FROM users WHERE username=%s", (owner,)
        ).fetchone()["id"]
        for i, name in enumerate(names):
            rid = f"rep-{i}"
            conn.execute(
                "INSERT INTO reports (id, name, created_by) VALUES (%s, %s, %s)",
                (rid, name, uid),
            )
            conn.execute(
                "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
                "pdf_sha256, pdf_path, status, uploaded_at, created_by) VALUES "
                "(%s, %s, 1, 'initial', %s, %s, 'x.pdf', 'completed', %s, %s)",
                (f"run-{i}", rid, name, f"sha{i}", f"2026-06-{i + 1:02d}T00:00:00Z", uid),
            )


def test_list_reports_paginates(auth_client):
    _seed_reports([f"report-{i}.pdf" for i in range(5)])

    first = auth_client.get("/api/reports", params={"limit": 2, "offset": 0}).json()
    assert first["total"] == 5, "total counts every match, not just this page"
    assert first["limit"] == 2 and first["offset"] == 0
    assert len(first["items"]) == 2

    second = auth_client.get("/api/reports", params={"limit": 2, "offset": 2}).json()
    assert second["total"] == 5
    assert {r["id"] for r in first["items"]}.isdisjoint({r["id"] for r in second["items"]})

    last = auth_client.get("/api/reports", params={"limit": 2, "offset": 4}).json()
    assert len(last["items"]) == 1


def test_pages_cover_every_report_exactly_once(auth_client):
    _seed_reports([f"report-{i}.pdf" for i in range(5)])
    seen = []
    for offset in (0, 2, 4):
        seen += [r["id"] for r in
                 auth_client.get("/api/reports", params={"limit": 2, "offset": offset}).json()["items"]]
    assert len(seen) == len(set(seen)) == 5


def test_list_reports_orders_newest_activity_first(auth_client):
    _seed_reports(["oldest.pdf", "middle.pdf", "newest.pdf"])
    items = auth_client.get("/api/reports").json()["items"]
    assert [r["name"] for r in items] == ["newest.pdf", "middle.pdf", "oldest.pdf"]


def test_search_matches_report_name_case_insensitively(auth_client):
    _seed_reports(["ABMM Platinum.pdf", "PTVI Nickel.pdf"])
    body = auth_client.get("/api/reports", params={"q": "platinum"}).json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "ABMM Platinum.pdf"


def test_search_total_reflects_the_filter_not_the_whole_table(auth_client):
    """`total` drives "Page 1 of N" — if it ignored `q` the pager would offer
    pages that come back empty."""
    _seed_reports([f"report-{i}.pdf" for i in range(5)] + ["unique-one.pdf"])
    body = auth_client.get("/api/reports", params={"q": "unique"}).json()
    assert body["total"] == 1


def test_search_matches_the_pdf_filename_after_a_rename(auth_client):
    _seed_reports(["original-name.pdf"])
    auth_client.patch("/api/reports/rep-0", json={"name": "Q3 draft"})
    body = auth_client.get("/api/reports", params={"q": "original-name"}).json()
    assert [r["name"] for r in body["items"]] == ["Q3 draft"]


def test_search_treats_wildcards_as_literal_text(auth_client):
    """A bare '%' must not match everything.

    ILIKE would read it as "any characters", so an unescaped query turns a
    typo into a full table scan that looks like the filter silently failing.
    """
    _seed_reports([f"report-{i}.pdf" for i in range(3)])
    assert auth_client.get("/api/reports", params={"q": "%"}).json()["total"] == 0
    assert auth_client.get("/api/reports", params={"q": "_"}).json()["total"] == 0
    assert auth_client.get("/api/reports", params={"q": "\\"}).json()["total"] == 0


def test_search_respects_ownership(auth_client, second_user_client):
    _seed_reports(["secret-report.pdf"], owner="tester")
    assert auth_client.get("/api/reports", params={"q": "secret"}).json()["total"] == 1
    assert second_user_client.get("/api/reports", params={"q": "secret"}).json()["total"] == 0


def test_pagination_bounds_are_enforced(auth_client):
    assert auth_client.get("/api/reports", params={"limit": 0}).status_code == 422
    assert auth_client.get("/api/reports", params={"limit": 101}).status_code == 422
    assert auth_client.get("/api/reports", params={"offset": -1}).status_code == 422


def test_offset_past_the_end_returns_an_empty_page_not_an_error(auth_client):
    _seed_reports(["only.pdf"])
    body = auth_client.get("/api/reports", params={"offset": 500}).json()
    assert body["items"] == []
    assert body["total"] == 1
