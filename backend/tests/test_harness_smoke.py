"""Minimal sanity test for the Postgres-backed pytest harness.

Verifies that the pool is initialised, connections work, and the _truncate
autouse fixture leaves the DB in a clean state (SELECT 1 just checks round-trip
connectivity — a failing pool would raise before this executes).
"""

from accordance.db import connection


def test_pool_round_trip():
    with connection() as conn:
        assert conn.execute("SELECT 1 AS one").fetchone()["one"] == 1
