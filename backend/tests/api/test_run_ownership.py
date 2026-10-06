from accordance.api.runs import _open_conn
from accordance.config import get_settings
from accordance.db import connection


def _make_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n%%EOF\n"


def test_create_run_stamps_created_by(auth_client):
    r = auth_client.post(
        "/api/runs",
        files={"pdf": ("doc.pdf", _make_pdf_bytes(), "application/pdf")},
    )
    assert r.status_code in (200, 201)
    run_id = r.json()["run_id"]

    with _open_conn(get_settings()) as conn:
        row = conn.execute(
            "SELECT r.created_by AS cb, u.username AS un "
            "FROM runs r JOIN users u ON u.id = r.created_by WHERE r.id=%s",
            (run_id,),
        ).fetchone()
    assert row is not None
    assert row["un"] == "tester"


def _seed(rep_id: str, run_id: str) -> None:
    """Insert a report owned by 'tester' + a run + a correction under it."""
    with connection() as conn:
        uid = conn.execute("SELECT id FROM users WHERE username='tester'").fetchone()["id"]
        conn.execute(
            "INSERT INTO reports (id, name, created_by) VALUES (%s, 'r', %s)",
            (rep_id, uid),
        )
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status, created_by) VALUES "
            "(%s, %s, 1, 'initial', 'f.pdf', 's', 'p', 'completed', %s)",
            (run_id, rep_id, uid),
        )
        conn.execute(
            "INSERT INTO assessor_corrections "
            "(run_id, disclosure_id, standard, corrected_score, corrected_elements_json, "
            " rationale, agent_score, agent_status, prompt_hash, model, chunk_ids_json, "
            " pages_json, reviewer) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (run_id, "2-1", "GRI 2", 5, None, "ok", None, None, None, None, "[]", "[]", "tester"),
        )


def test_second_user_gets_404_on_get_run(auth_client, second_user_client):
    _seed("ro_rep_a", "ro_run_a")
    assert second_user_client.get("/api/runs/ro_run_a").status_code == 404


def test_second_user_gets_404_on_get_run_pdf(auth_client, second_user_client):
    _seed("ro_rep_b", "ro_run_b")
    assert second_user_client.get("/api/runs/ro_run_b/pdf").status_code == 404


def test_second_user_gets_404_on_delete_run(auth_client, second_user_client):
    _seed("ro_rep_c", "ro_run_c")
    assert second_user_client.delete("/api/runs/ro_run_c").status_code == 404


def test_second_user_gets_404_on_stop_run(auth_client, second_user_client):
    _seed("ro_rep_d", "ro_run_d")
    assert second_user_client.post("/api/runs/ro_run_d/stop").status_code == 404


def test_second_user_gets_404_on_list_corrections(auth_client, second_user_client):
    _seed("ro_rep_e", "ro_run_e")
    assert second_user_client.get("/api/runs/ro_run_e/corrections").status_code == 404


def test_second_user_gets_404_on_delete_correction(auth_client, second_user_client):
    _seed("ro_rep_f", "ro_run_f")
    with connection() as conn:
        cid = conn.execute(
            "SELECT id FROM assessor_corrections WHERE run_id=%s LIMIT 1", ("ro_run_f",)
        ).fetchone()["id"]
    assert second_user_client.delete(f"/api/runs/ro_run_f/corrections/{cid}").status_code == 404


def test_second_user_gets_404_on_judge_more(auth_client, second_user_client):
    _seed("ro_rep_g", "ro_run_g")
    assert (
        second_user_client.post(
            "/api/runs/ro_run_g/judge-more",
            json={"disclosure_ids": ["2-1"]},
        ).status_code
        == 404
    )


def test_second_user_gets_404_on_retry(auth_client, second_user_client):
    _seed("ro_rep_h", "ro_run_h")
    assert second_user_client.post("/api/runs/ro_run_h/retry").status_code == 404


def test_admin_can_read_any_run(auth_client, admin_client):
    _seed("ro_rep_i", "ro_run_i")
    assert admin_client.get("/api/runs/ro_run_i").status_code == 200
