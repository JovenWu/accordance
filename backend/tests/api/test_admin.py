import pytest
from fastapi.testclient import TestClient

from accordance.auth.passwords import hash_password
from accordance.config import get_settings
from accordance.db import connection
from accordance.main import create_app


@pytest.fixture
def admin_client(tmp_path, monkeypatch):
    """A TestClient logged in as a seeded admin user."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    get_settings.cache_clear()
    with connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, TRUE)",
            ("admin", hash_password("password1")),
        )
    client = TestClient(create_app())
    client.post("/api/auth/login", json={"username": "admin", "password": "password1"})
    return client


def test_list_requires_admin(auth_client):
    # auth_client (from tests/api/conftest.py) is the non-admin 'tester'.
    assert auth_client.get("/api/admin/users").status_code == 403


def test_list_users_with_stats(admin_client):
    with connection() as conn:
        uid = conn.execute(
            "SELECT id FROM users WHERE username='admin'"
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO run_completions (run_id, user_id) VALUES ('r1', %s)", (uid,)
        )
        conn.execute(
            "INSERT INTO run_completions (run_id, user_id) VALUES ('r2', %s)", (uid,)
        )
        conn.execute(
            "INSERT INTO llm_usage (run_id, user_id, kind, model, cost_usd) "
            "VALUES ('r1', %s, 'judge', 'm', 1.50)",
            (uid,),
        )
        conn.execute(
            "INSERT INTO llm_usage (run_id, user_id, kind, model, cost_usd) "
            "VALUES ('r2', %s, 'judge', 'm', 0.50)",
            (uid,),
        )
    r = admin_client.get("/api/admin/users")
    assert r.status_code == 200
    by_name = {u["username"]: u for u in r.json()}
    assert by_name["admin"]["pdf_count"] == 2
    assert round(by_name["admin"]["cost_usd"], 2) == 2.00
    assert by_name["admin"]["is_admin"] is True
    assert by_name["admin"]["is_active"] is True


def test_create_user(admin_client):
    r = admin_client.post(
        "/api/admin/users", json={"username": "newbie", "password": "password1"}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "newbie"
    assert body["is_admin"] is False
    assert body["pdf_count"] == 0
    assert body["cost_usd"] == 0.0


def test_create_duplicate_409(admin_client):
    admin_client.post(
        "/api/admin/users", json={"username": "dup", "password": "password1"}
    )
    r = admin_client.post(
        "/api/admin/users", json={"username": "dup", "password": "password1"}
    )
    assert r.status_code == 409


def test_create_short_password_400(admin_client):
    r = admin_client.post(
        "/api/admin/users", json={"username": "x", "password": "short"}
    )
    assert r.status_code == 400


def test_create_requires_admin(auth_client):
    r = auth_client.post(
        "/api/admin/users", json={"username": "y", "password": "password1"}
    )
    assert r.status_code == 403


def test_disable_and_enable_user(admin_client):
    admin_client.post(
        "/api/admin/users", json={"username": "target", "password": "password1"}
    )
    with connection() as conn:
        uid = conn.execute(
            "SELECT id FROM users WHERE username='target'"
        ).fetchone()["id"]

    r = admin_client.patch(f"/api/admin/users/{uid}", json={"is_active": False})
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    r2 = admin_client.patch(f"/api/admin/users/{uid}", json={"is_active": True})
    assert r2.status_code == 200
    assert r2.json()["is_active"] is True


def test_cannot_disable_self(admin_client):
    with connection() as conn:
        uid = conn.execute(
            "SELECT id FROM users WHERE username='admin'"
        ).fetchone()["id"]
    r = admin_client.patch(f"/api/admin/users/{uid}", json={"is_active": False})
    assert r.status_code == 400


def test_patch_unknown_user_404(admin_client):
    r = admin_client.patch("/api/admin/users/99999", json={"is_active": False})
    assert r.status_code == 404


def test_promote_and_demote_user(admin_client):
    admin_client.post(
        "/api/admin/users", json={"username": "promoteme", "password": "password1"}
    )
    with connection() as conn:
        uid = conn.execute(
            "SELECT id FROM users WHERE username='promoteme'"
        ).fetchone()["id"]

    r = admin_client.patch(f"/api/admin/users/{uid}", json={"is_admin": True})
    assert r.status_code == 200
    assert r.json()["is_admin"] is True

    r2 = admin_client.patch(f"/api/admin/users/{uid}", json={"is_admin": False})
    assert r2.status_code == 200
    assert r2.json()["is_admin"] is False


def test_cannot_demote_self(admin_client):
    with connection() as conn:
        uid = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]
    r = admin_client.patch(f"/api/admin/users/{uid}", json={"is_admin": False})
    assert r.status_code == 400


def test_patch_requires_a_field(admin_client):
    with connection() as conn:
        uid = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]
    r = admin_client.patch(f"/api/admin/users/{uid}", json={})
    assert r.status_code == 400


def test_get_user_detail(admin_client):
    admin_client.post(
        "/api/admin/users", json={"username": "deep", "password": "password1"}
    )
    with connection() as conn:
        uid = conn.execute("SELECT id FROM users WHERE username='deep'").fetchone()["id"]
        conn.execute(
            "INSERT INTO reports (id, name, created_by) VALUES ('rep1', 'R', %s)", (uid,)
        )
        conn.execute(
            "INSERT INTO runs (id, report_id, created_by, pdf_filename, status, completed_at, "
            "version_number, kind, pdf_sha256, pdf_path) "
            "VALUES ('run1', 'rep1', %s, 'a.pdf', 'completed', now(), 1, 'initial', 'fake_sha256', 'fake_path')",
            (uid,),
        )
        conn.execute("INSERT INTO run_completions (run_id, user_id) VALUES ('run1', %s)", (uid,))
        conn.execute(
            "INSERT INTO llm_usage (run_id, user_id, kind, model, cost_usd) "
            "VALUES ('run1', %s, 'judge', 'm', 1.25)",
            (uid,),
        )
        conn.execute(
            "INSERT INTO llm_usage (run_id, user_id, kind, model, cost_usd) "
            "VALUES ('run1', %s, 'embedding', 'm', 0.25)",
            (uid,),
        )

    r = admin_client.get(f"/api/admin/users/{uid}")
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "deep"
    assert body["pdf_count"] == 1
    assert round(body["cost_usd"], 2) == 1.50
    assert body["last_active"] is not None
    kinds = {k["kind"]: k for k in body["cost_by_kind"]}
    assert round(kinds["judge"]["cost_usd"], 2) == 1.25
    assert kinds["judge"]["call_count"] == 1
    assert len(body["recent_runs"]) == 1
    assert body["recent_runs"][0]["pdf_filename"] == "a.pdf"
    assert round(body["recent_runs"][0]["run_cost_usd"], 2) == 1.50


def test_get_user_detail_404(admin_client):
    assert admin_client.get("/api/admin/users/99999").status_code == 404


def test_get_user_detail_requires_admin(auth_client):
    assert auth_client.get("/api/admin/users/1").status_code == 403


def test_reset_password(admin_client):
    admin_client.post(
        "/api/admin/users", json={"username": "resetme", "password": "password1"}
    )
    with connection() as conn:
        uid = conn.execute("SELECT id FROM users WHERE username='resetme'").fetchone()["id"]

    r = admin_client.post(
        f"/api/admin/users/{uid}/reset-password", json={"password": "newpass99"}
    )
    assert r.status_code == 204

    from accordance.main import create_app

    fresh = TestClient(create_app())
    assert fresh.post(
        "/api/auth/login", json={"username": "resetme", "password": "newpass99"}
    ).status_code == 200
    assert fresh.post(
        "/api/auth/login", json={"username": "resetme", "password": "password1"}
    ).status_code == 401


def test_reset_password_short_400(admin_client):
    with connection() as conn:
        # NOTE: test_admin.py defines its OWN admin_client fixture seeding 'admin'
        # (it shadows conftest's 'boss'). Use 'admin' here, not 'boss'.
        uid = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]
    r = admin_client.post(
        f"/api/admin/users/{uid}/reset-password", json={"password": "short"}
    )
    assert r.status_code == 400


def test_reset_password_404(admin_client):
    r = admin_client.post(
        "/api/admin/users/99999/reset-password", json={"password": "newpass99"}
    )
    assert r.status_code == 404


def test_reset_password_invalidates_existing_sessions(admin_client):
    admin_client.post(
        "/api/admin/users", json={"username": "sessuser", "password": "password1"}
    )
    victim = TestClient(create_app())
    assert victim.post(
        "/api/auth/login", json={"username": "sessuser", "password": "password1"}
    ).status_code == 200
    assert victim.get("/api/auth/me").status_code == 200  # session valid before reset

    with connection() as conn:
        uid = conn.execute(
            "SELECT id FROM users WHERE username='sessuser'"
        ).fetchone()["id"]
    admin_client.post(
        f"/api/admin/users/{uid}/reset-password", json={"password": "newpass99"}
    )

    # The victim's pre-reset session is now invalid.
    assert victim.get("/api/auth/me").status_code == 401


def _uid(conn, username="admin"):
    return conn.execute("SELECT id FROM users WHERE username=%s", (username,)).fetchone()["id"]


def test_daily_usage_buckets_by_wib_day_not_utc(admin_client):
    """Day buckets must use the app's display timezone (WIB), not UTC.

    The drawer renders every other timestamp in Asia/Jakarta, so a 23:00 WIB
    run — 16:00 UTC the same day — has to land on the WIB date. Grouping in UTC
    would file it under the day before the one its own "Recent runs" row shows.
    """
    with connection() as conn:
        uid = _uid(conn)
        # 2026-03-10 16:30Z == 2026-03-10 23:30 WIB -> still the 10th locally.
        conn.execute(
            "INSERT INTO llm_usage (run_id, user_id, kind, model, cost_usd, created_at) "
            "VALUES ('d1', %s, 'judge', 'm', 1.00, '2026-03-10T16:30:00Z')",
            (uid,),
        )
        # 2026-03-10 18:00Z == 2026-03-11 01:00 WIB -> rolls into the 11th.
        conn.execute(
            "INSERT INTO llm_usage (run_id, user_id, kind, model, cost_usd, created_at) "
            "VALUES ('d2', %s, 'judge', 'm', 2.00, '2026-03-10T18:00:00Z')",
            (uid,),
        )

    days = admin_client.get(f"/api/admin/users/{uid}").json()["daily_usage"]
    by_day = {d["day"]: d["cost_usd"] for d in days}
    assert by_day == {"2026-03-10": 1.00, "2026-03-11": 2.00}


def test_daily_usage_keeps_days_that_only_one_log_saw(admin_client):
    """Completions and cost are separate logs with independent timestamps.

    A run can complete on a day whose tokens were all booked earlier, and a
    retry books cost against a run completed days before. An inner join would
    silently drop whichever side is missing.
    """
    with connection() as conn:
        uid = _uid(conn)
        conn.execute(
            "INSERT INTO run_completions (run_id, user_id, completed_at) "
            "VALUES ('c1', %s, '2026-04-01T03:00:00Z')",
            (uid,),
        )
        conn.execute(
            "INSERT INTO llm_usage (run_id, user_id, kind, model, cost_usd, created_at) "
            "VALUES ('c2', %s, 'judge', 'm', 0.50, '2026-04-05T03:00:00Z')",
            (uid,),
        )

    days = {d["day"]: d for d in admin_client.get(f"/api/admin/users/{uid}").json()["daily_usage"]}
    # Completions-only day survives with a zeroed cost...
    assert days["2026-04-01"]["pdf_count"] == 1
    assert days["2026-04-01"]["cost_usd"] == 0.0
    # ...and the cost-only day survives with no PDFs.
    assert days["2026-04-05"]["pdf_count"] == 0
    assert days["2026-04-05"]["cost_usd"] == 0.5


def test_daily_usage_is_newest_first_and_omits_quiet_days(admin_client):
    with connection() as conn:
        uid = _uid(conn)
        for run, day in (("a", "2026-05-01"), ("b", "2026-05-09")):
            conn.execute(
                "INSERT INTO llm_usage (run_id, user_id, kind, model, cost_usd, created_at) "
                "VALUES (%s, %s, 'judge', 'm', 0.25, %s)",
                (run, uid, f"{day}T03:00:00Z"),
            )

    days = admin_client.get(f"/api/admin/users/{uid}").json()["daily_usage"]
    # The 7 days in between had no activity and must not appear as zero rows.
    assert [d["day"] for d in days] == ["2026-05-09", "2026-05-01"]


def test_daily_usage_is_empty_for_a_user_with_no_activity(admin_client):
    with connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            ("quiet", hash_password("password1")),
        )
        uid = _uid(conn, "quiet")
    assert admin_client.get(f"/api/admin/users/{uid}").json()["daily_usage"] == []
