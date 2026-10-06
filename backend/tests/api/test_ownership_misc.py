"""Task 18: ownership scoping for versioning/traces/export/stream endpoints."""

from accordance.db import connection


def _seed_owned(rep_id: str, run_id: str, status: str = "completed") -> None:
    """Insert a report + run owned by the 'tester' user."""
    with connection() as conn:
        uid = conn.execute("SELECT id FROM users WHERE username='tester'").fetchone()["id"]
        conn.execute(
            "INSERT INTO reports (id, name, created_by) VALUES (%s, 'x', %s)",
            (rep_id, uid),
        )
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status, created_by) VALUES "
            "(%s, %s, 1, 'initial', 'f.pdf', 'sha', 'p', %s, %s)",
            (run_id, rep_id, status, uid),
        )


def test_fork_second_user_gets_404(auth_client, second_user_client):
    _seed_owned("misc_rep_fork", "misc_run_fork")
    assert second_user_client.post("/api/runs/misc_run_fork/fork").status_code == 404


def test_versions_second_user_gets_404(auth_client, second_user_client):
    _seed_owned("misc_rep_ver", "misc_run_ver")
    assert (
        second_user_client.post(
            "/api/reports/misc_rep_ver/versions",
            files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        ).status_code
        == 404
    )


def test_traces_second_user_gets_404(auth_client, second_user_client):
    _seed_owned("misc_rep_tr", "misc_run_tr")
    assert second_user_client.get("/api/runs/misc_run_tr/traces").status_code == 404


def test_run_export_second_user_gets_404(auth_client, second_user_client):
    _seed_owned("misc_rep_ex1", "misc_run_ex1")
    assert second_user_client.get("/api/runs/misc_run_ex1/export/coverage").status_code == 404


def test_report_export_second_user_gets_404(auth_client, second_user_client):
    _seed_owned("misc_rep_ex2", "misc_run_ex2")
    assert second_user_client.get("/api/reports/misc_rep_ex2/export/coverage").status_code == 404


def test_stream_second_user_gets_404(auth_client, second_user_client):
    _seed_owned("misc_rep_st", "misc_run_st")
    assert second_user_client.get("/api/runs/misc_run_st/stream").status_code == 404


def test_export_options_only_shows_own_reports(auth_client, second_user_client):
    _seed_owned("misc_rep_opt", "misc_run_opt")
    resp = second_user_client.get("/api/reports/export/options")
    assert resp.status_code == 200
    assert all(d["report_id"] != "misc_rep_opt" for d in resp.json())
    resp = auth_client.get("/api/reports/export/options")
    assert any(d["report_id"] == "misc_rep_opt" for d in resp.json())


def test_export_selected_second_user_gets_404(auth_client, second_user_client):
    _seed_owned("misc_rep_sel", "misc_run_sel")
    assert (
        second_user_client.get("/api/reports/export/coverage?runs=misc_run_sel").status_code == 404
    )


def test_export_selected_mixed_batch_gets_404(auth_client, second_user_client):
    """Batch export aborts with 404 when a user mixes their own run with another user's run."""
    _seed_owned("misc_rep_mix_t", "misc_run_mix_t")
    with connection() as conn:
        uid = conn.execute("SELECT id FROM users WHERE username='other'").fetchone()["id"]
        conn.execute(
            "INSERT INTO reports (id, name, created_by) VALUES (%s, 'y', %s)",
            ("misc_rep_mix_o", uid),
        )
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status, created_by) VALUES "
            "(%s, %s, 1, 'initial', 'g.pdf', 'sha2', 'p2', 'completed', %s)",
            ("misc_run_mix_o", "misc_rep_mix_o", uid),
        )
    resp = second_user_client.get("/api/reports/export/coverage?runs=misc_run_mix_o,misc_run_mix_t")
    assert resp.status_code == 404
