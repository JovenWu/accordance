from accordance import db
from accordance.graph.nodes import _record_completion


def test_record_completion_writes_one_owned_row():
    with db.connection() as conn:
        conn.execute("INSERT INTO users (username, password_hash) VALUES ('u','h')")
        uid = conn.execute("SELECT id FROM users WHERE username='u'").fetchone()["id"]
        conn.execute("INSERT INTO reports (id, name) VALUES ('rep','d.pdf')")
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status, created_by) "
            "VALUES ('run1', 'rep', 1, 'initial', 'd.pdf', 's', '/x.pdf', 'completed', %s)",
            (uid,),
        )

        _record_completion(conn, "run1")
        _record_completion(conn, "run1")

        rows = conn.execute("SELECT user_id FROM run_completions WHERE run_id='run1'").fetchall()
        assert len(rows) == 1
        assert rows[0]["user_id"] == uid
