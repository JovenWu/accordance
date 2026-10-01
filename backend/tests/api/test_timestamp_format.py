"""Verify timestamp wire format survives the SQLite→Postgres change.

psycopg returns TIMESTAMPTZ columns as Python ``datetime``; SQLite used to
return plain strings. Pydantic serialises datetime → ISO-8601 with a ``T``
separator (and an optional UTC offset). The frontend ``parseServerDate``
helper accepts both formats, so the offset suffix is harmless.

These tests assert the on-wire values already satisfy the regex the frontend
relies on, so a future ORM or serialiser change can't silently break it.
"""

import re

from accordance.db import connection

# Matches ISO-8601 date+time with a T separator, e.g.
#   "2026-06-28T14:23:01"
#   "2026-06-28T14:23:01.123456"
#   "2026-06-28T14:23:01+00:00"
_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _seed(uid: int) -> None:
    """Insert a minimal report + run owned by *uid* into the test database."""
    with connection() as conn:
        conn.execute(
            "INSERT INTO reports (id, name, created_by) VALUES (%s, %s, %s)",
            ("rep-ts", "ts-test.pdf", uid),
        )
        conn.execute(
            "INSERT INTO runs "
            "(id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                "run-ts",
                "rep-ts",
                1,
                "initial",
                "ts-test.pdf",
                "sha256abc",
                "/pdf/ts-test.pdf",
                "completed",
                uid,
            ),
        )


def test_report_created_at_is_iso_parseable(auth_client):
    """GET /api/reports → created_at and latest.uploaded_at are ISO-8601 with T."""
    with connection() as conn:
        row = conn.execute("SELECT id FROM users WHERE username=%s", ("tester",)).fetchone()
    uid = row["id"]
    _seed(uid)

    r = auth_client.get("/api/reports")
    assert r.status_code == 200
    reports = r.json()["items"]
    assert len(reports) >= 1, "No reports returned — seed may have failed"

    for rep in reports:
        assert _ISO_RE.match(rep["created_at"]), (
            f"report created_at not ISO-8601 with T: {rep['created_at']!r}"
        )
        assert _ISO_RE.match(rep["latest"]["uploaded_at"]), (
            f"run uploaded_at not ISO-8601 with T: {rep['latest']['uploaded_at']!r}"
        )
