"""Task 15 - report ownership: reports.created_by is stamped at upload.
Task 16 - scoping: users see only their own reports; admins see all.
"""

from pathlib import Path

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_report.pdf"


def _upload_minimal_report(client) -> str:
    """Upload the sample PDF and return the new report_id.

    The multipart shape is copied verbatim from test_runs_upload.py so we
    don't accidentally invent field names.
    """
    with FIXTURE.open("rb") as f:
        r = client.post("/api/runs", files={"pdf": ("sample.pdf", f, "application/pdf")})
    assert r.status_code == 201, f"upload failed: {r.status_code} {r.text}"
    return r.json()["report_id"]


def test_uploaded_report_is_owned_by_creator(auth_client):
    """reports.created_by must equal the uploading user's id."""
    rep_id = _upload_minimal_report(auth_client)

    from accordance.db import connection

    with connection() as conn:
        owner = conn.execute("SELECT created_by FROM reports WHERE id=%s", (rep_id,)).fetchone()[
            "created_by"
        ]
        tester = conn.execute("SELECT id FROM users WHERE username='tester'").fetchone()["id"]

    assert owner == tester, f"expected created_by={tester!r}, got {owner!r}"


def _seed_owned_report(username: str, rep_id: str) -> None:
    from accordance.db import connection

    with connection() as conn:
        uid = conn.execute("SELECT id FROM users WHERE username=%s", (username,)).fetchone()["id"]
        conn.execute(
            "INSERT INTO reports (id, name, created_by) VALUES (%s, 'r', %s)", (rep_id, uid)
        )
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status, created_by) VALUES "
            "(%s, %s, 1, 'initial', 'f.pdf', 's', 'p', 'completed', %s)",
            (rep_id + "_run", rep_id, uid),
        )


def test_user_cannot_see_others_report(auth_client, second_user_client):
    _seed_owned_report("tester", "repX")
    assert any(r["id"] == "repX" for r in auth_client.get("/api/reports").json()["items"])
    assert all(r["id"] != "repX" for r in second_user_client.get("/api/reports").json()["items"])
    assert second_user_client.get("/api/reports/repX").status_code == 404
    assert second_user_client.delete("/api/reports/repX").status_code == 404
    assert second_user_client.patch("/api/reports/repX", json={"name": "x"}).status_code == 404
    assert (
        second_user_client.get(
            "/api/reports/repX/compare", params={"a": "ra", "b": "rb"}
        ).status_code
        == 404
    )


def test_admin_sees_all_reports(auth_client, admin_client):
    _seed_owned_report("tester", "repY")
    assert any(r["id"] == "repY" for r in admin_client.get("/api/reports").json()["items"])
    assert admin_client.get("/api/reports/repY").status_code == 200


def test_new_user_with_no_reports_gets_empty_list(second_user_client):
    """A freshly-logged-in user who owns no reports must get 200 [] — not an error."""
    resp = second_user_client.get("/api/reports")
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["items"] == [], f"expected empty page, got {body!r}"
    assert body["total"] == 0
