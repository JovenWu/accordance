from fastapi.testclient import TestClient

from accordance.auth.passwords import hash_password
from accordance.db import connection
from accordance.main import create_app


def _login(client):
    with connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            ("tester", hash_password("pw")),
        )
    client.post("/api/auth/login", json={"username": "tester", "password": "pw"})


def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")


def _seed(*, with_trace=False):
    with connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            ("tester", hash_password("pw")),
        )
        uid = conn.execute("SELECT id FROM users WHERE username='tester'").fetchone()["id"]
        conn.execute(
            "INSERT INTO reports (id, name, created_by) VALUES (%s, %s, %s)",
            ("rep", "x.pdf", uid),
        )
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            ("run1", "rep", 1, "initial", "x.pdf", "sha", "x.pdf", "completed", uid),
        )
        conn.execute(
            "INSERT INTO findings (run_id, disclosure_id, standard, status, score, "
            "note, elements_json, suggested_fix) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            ("run1", "2-1", "GRI 2", "partial", 3, "n", "[]", "f"),
        )
        if with_trace:
            conn.execute(
                "INSERT INTO judge_traces (run_id, disclosure_id, attempt, rejudged, "
                "prompt_hash, model, queries_json, chunk_ids_json, distances_json, "
                "pages_json, parse_path, error, latency_ms) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    "run1",
                    "2-1",
                    1,
                    False,
                    "ph9",
                    "gpt-5-mini",
                    "[]",
                    "[7,8]",
                    "[]",
                    "[80]",
                    "structured",
                    None,
                    10,
                ),
            )


def test_correction_records_logged_in_user_as_reviewer(auth_client, tmp_path):
    auth_client.get("/api/kb")
    _seed(with_trace=True)  # adds report 'rep' + run 'run1' + finding '2-1'
    r = auth_client.post(
        "/api/runs/run1/corrections",
        json={"disclosure_id": "2-1", "corrected_score": 5, "rationale": "p.80"},
    )
    assert r.status_code == 201
    assert r.json()["reviewer"] == "tester"  # the logged-in user, not "assessor"


def test_post_correction_creates_and_snapshots(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")
    _seed(with_trace=True)
    r = client.post(
        "/api/runs/run1/corrections",
        json={
            "disclosure_id": "2-1",
            "corrected_score": 5,
            "rationale": "Base year IS on p.80.",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["corrected_score"] == 5
    assert body["agent_score"] == 3
    assert body["rationale"] == "Base year IS on p.80."
    assert body["reviewer"] == "tester"


def test_post_correction_supersedes_prior(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")
    _seed()
    client.post(
        "/api/runs/run1/corrections",
        json={"disclosure_id": "2-1", "corrected_score": 4, "rationale": "a"},
    )
    client.post(
        "/api/runs/run1/corrections",
        json={"disclosure_id": "2-1", "corrected_score": 5, "rationale": "b"},
    )
    with connection() as conn:
        live = conn.execute(
            "SELECT corrected_score FROM assessor_corrections "
            "WHERE run_id='run1' AND disclosure_id='2-1' AND superseded=FALSE"
        ).fetchall()
    assert len(live) == 1
    assert live[0]["corrected_score"] == 5


def test_post_correction_validation(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")
    _seed()
    assert (
        client.post(
            "/api/runs/nope/corrections",
            json={"disclosure_id": "2-1", "corrected_score": 5, "rationale": "x"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/runs/run1/corrections",
            json={"disclosure_id": "ZZZ", "corrected_score": 5, "rationale": "x"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/runs/run1/corrections",
            json={"disclosure_id": "2-1", "corrected_score": 5, "rationale": ""},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/runs/run1/corrections",
            json={"disclosure_id": "2-1", "corrected_score": 7, "rationale": "x"},
        ).status_code
        == 422
    )


def test_get_and_get_run_return_live_corrections(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")
    _seed()
    client.post(
        "/api/runs/run1/corrections",
        json={"disclosure_id": "2-1", "corrected_score": 5, "rationale": "ok"},
    )
    listed = client.get("/api/runs/run1/corrections").json()
    assert len(listed) == 1 and listed[0]["corrected_score"] == 5
    detail = client.get("/api/runs/run1").json()
    assert len(detail["corrections"]) == 1
    assert detail["corrections"][0]["disclosure_id"] == "2-1"


def test_uncorrected_run_has_empty_corrections(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")
    _seed()
    listed = client.get("/api/runs/run1/corrections").json()
    assert listed == []
    detail = client.get("/api/runs/run1").json()
    assert detail["corrections"] == []


def test_delete_correction_soft_retires(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    client = TestClient(create_app())
    _login(client)
    client.get("/api/kb")
    _seed()
    cid = client.post(
        "/api/runs/run1/corrections",
        json={"disclosure_id": "2-1", "corrected_score": 5, "rationale": "ok"},
    ).json()["id"]
    assert client.delete(f"/api/runs/run1/corrections/{cid}").status_code == 204
    assert client.get("/api/runs/run1/corrections").json() == []
    assert client.delete("/api/runs/run1/corrections/9999").status_code == 404
