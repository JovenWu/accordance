"""A failed run must publish a terminal SSE event.

Without it the /stream generator only returns on 'completed'/'cancelled', so a
watched failed run leaks an open connection + subscriber queue forever. The
worker's failure handler now publishes {"type": "failed"} and stream.py treats
it as terminal.
"""

from accordance.api import events as events_mod
from accordance.api import runs as runs_mod
from accordance.config import get_settings


def test_failed_worker_publishes_failed_event(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    get_settings.cache_clear()

    settings = get_settings()
    with runs_mod._open_conn(settings) as conn:
        conn.execute("INSERT INTO reports (id, name) VALUES ('rep1', 'r.pdf')")
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status) "
            "VALUES ('run1', 'rep1', 1, 'initial', 'r.pdf', 'sha1', %s, 'queued')",
            (str(tmp_path / "run1.pdf"),),
        )

    events = []
    monkeypatch.setattr(
        events_mod.bus, "publish", lambda rid, ev: events.append((rid, ev))
    )

    def boom(**kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr("accordance.graph.build.run_graph", boom)

    runs_mod._kick_off_graph("run1", tmp_path / "run1.pdf", settings)
    runs_mod.drain_active_runs(timeout=10)

    with runs_mod._open_conn(settings) as conn:
        status = conn.execute(
            "SELECT status FROM runs WHERE id='run1'"
        ).fetchone()["status"]

    assert status == "failed"
    assert ("run1", {"type": "failed"}) in events


def test_stream_treats_failed_as_terminal():
    import inspect

    from accordance.api import stream

    src = inspect.getsource(stream.stream_run)
    assert '"failed"' in src
