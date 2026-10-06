from accordance.db import connection


def _uid(conn, username="tester"):
    return conn.execute(
        "SELECT id FROM users WHERE username=%s", (username,)
    ).fetchone()["id"]


def test_me_stats_sums_completions_and_cost_for_current_user(auth_client):
    with connection() as conn:
        uid = _uid(conn)
        conn.execute(
            "INSERT INTO run_completions (run_id, user_id) VALUES ('a', %s) "
            "ON CONFLICT DO NOTHING",
            (uid,),
        )
        conn.execute(
            "INSERT INTO run_completions (run_id, user_id) VALUES ('b', %s) "
            "ON CONFLICT DO NOTHING",
            (uid,),
        )
        conn.execute("INSERT INTO run_completions (run_id, user_id) VALUES (NULL, %s)", (uid,))
        conn.execute(
            "INSERT INTO llm_usage (run_id, user_id, kind, model, cost_usd)"
            " VALUES ('a', %s, 'judge', 'm', 1.25)",
            (uid,),
        )
        conn.execute(
            "INSERT INTO llm_usage (run_id, user_id, kind, model, cost_usd)"
            " VALUES ('a', %s, 'embedding', 'm', 0.05)",
            (uid,),
        )
        conn.execute(
            "INSERT INTO llm_usage (run_id, user_id, kind, model, cost_usd)"
            " VALUES (NULL, %s, 'judge', 'm', 0.10)",
            (uid,),
        )
        conn.execute("INSERT INTO users (username, password_hash) VALUES ('other','h')")
        oid = _uid(conn, "other")
        conn.execute("INSERT INTO run_completions (run_id, user_id) VALUES ('z', %s)", (oid,))
        conn.execute(
            "INSERT INTO llm_usage (run_id, user_id, kind, model, cost_usd)"
            " VALUES ('z', %s, 'judge', 'm', 99.0)",
            (oid,),
        )

    r = auth_client.get("/api/me/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["pdf_count"] == 3
    assert round(body["cost_usd"], 2) == 1.40


def test_me_stats_zero_for_new_user(auth_client):
    r = auth_client.get("/api/me/stats")
    assert r.status_code == 200
    assert r.json() == {"pdf_count": 0, "cost_usd": 0.0}


def test_me_stats_requires_auth():
    from fastapi.testclient import TestClient

    from accordance.main import create_app

    r = TestClient(create_app()).get("/api/me/stats")
    assert r.status_code == 401
