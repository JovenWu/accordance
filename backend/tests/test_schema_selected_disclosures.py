from accordance.db import connection, ensure_schema


def _has_column(conn, table: str, column: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s",
        (table, column),
    ).fetchone()
    return row is not None


def test_fresh_db_has_selected_disclosures_column():
    with connection() as conn:
        assert _has_column(conn, "runs", "selected_disclosures")


def test_existing_db_gets_column_added_idempotently():
    with connection() as conn:
        ensure_schema(conn)
        assert _has_column(conn, "runs", "selected_disclosures")
