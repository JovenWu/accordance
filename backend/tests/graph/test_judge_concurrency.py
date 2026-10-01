import threading
import time

from accordance import db
from accordance.graph import nodes as nodes_mod
from accordance.graph.nodes import judge_all_node
from accordance.indexer.chunker import Chunk
from accordance.indexer.embedder import FakeEmbedder
from accordance.indexer.vector_store import VectorStore
from accordance.kb.schema import Disclosure, RequiredElement
from accordance.llm.adapter import FakeJudgeLLM


def _disc(did: str) -> Disclosure:
    return Disclosure(
        id=did,
        standard="GRI 2",
        title=did,
        category="universal",
        requirement_text="r",
        required_elements=[RequiredElement(id="x", desc="x")],
        retrieval_queries=["q"],
        suggested_fix_template="fix",
    )


def test_judge_all_node_uses_per_thread_connections(monkeypatch):
    """The judge fan-out runs many disclosures over a ThreadPoolExecutor.
    Each worker must borrow its OWN connection from the Postgres pool — the
    shared outer connection must never appear in the worker set."""
    with db.connection() as conn:
        conn.execute("INSERT INTO reports (id, name) VALUES ('rep', 'x.pdf')")
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status) "
            "VALUES ('r1', 'rep', 1, 'initial', 'x.pdf', 'sha', 'x', 'judging')"
        )
        store = VectorStore(conn, FakeEmbedder(dim=8))
        store.write("r1", [Chunk(page=1, text="content")])
        disclosures = [_disc(f"2-{i}") for i in range(1, 9)]  # 8 disclosures, >max_workers

        seen_conn_ids: set[int] = set()
        lock = threading.Lock()

        def spy_judge_one(state, disclosure, store_, llm, conn_, **kw):
            with lock:
                seen_conn_ids.add(id(conn_))
            # Write through whatever connection the fan-out handed us — proves the
            # per-thread connection is usable for writes, and lets us assert no
            # finding was dropped.
            conn_.execute(
                "INSERT INTO findings (run_id, disclosure_id, standard, status, note, "
                "elements_json, suggested_fix) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (state["run_id"], disclosure.id, disclosure.standard, "partial", "n", "[]", "fix"),
            )
            return {"findings": [{"disclosure_id": disclosure.id}]}

        monkeypatch.setattr(nodes_mod, "judge_one_node", spy_judge_one)

        out = judge_all_node(
            {"run_id": "r1"},
            disclosures,
            store,
            FakeJudgeLLM(),
            conn,
            max_workers=4,
        )

        # No finding dropped.
        n = conn.execute("SELECT COUNT(*) AS n FROM findings WHERE run_id='r1'").fetchone()["n"]
        assert n == len(disclosures)
        assert len(out["findings"]) == len(disclosures)

        # The shared main connection must NOT be used by the workers.
        assert seen_conn_ids, "no judge_one_node calls observed"
        assert id(conn) not in seen_conn_ids, (
            "judge workers used the shared main connection — unsafe under "
            "Postgres connection pool semantics"
        )


def test_queued_workers_do_not_hold_db_connections(monkeypatch):
    """A worker waiting for an LLM slot must not occupy a Postgres connection.

    The fan-out starts judge_concurrency threads per run, but the judge
    semaphore is GLOBAL. Taking the connection before waiting on it meant
    every queued thread parked on a connection it wasn't using, so pool demand
    scaled as runs x judge_concurrency (138 connections for 10 runs x 12)
    while only judge_concurrency calls ever ran. Peak concurrent connections
    must track the semaphore, not the thread count.
    """
    import accordance.db as db_mod

    live = 0
    peak = 0
    lock = threading.Lock()
    real_connection = db_mod.connection

    class _Counting:
        def __enter__(self):
            nonlocal live, peak
            self._cm = real_connection()
            conn = self._cm.__enter__()
            with lock:
                live += 1
                peak = max(peak, live)
            return conn

        def __exit__(self, *exc):
            nonlocal live
            with lock:
                live -= 1
            return self._cm.__exit__(*exc)

    monkeypatch.setattr(nodes_mod, "db_connection", lambda: _Counting())

    with db.connection() as conn:
        conn.execute("INSERT INTO reports (id, name) VALUES ('rep-pool', 'x.pdf')")
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status) "
            "VALUES ('r-pool', 'rep-pool', 1, 'initial', 'x.pdf', 'sha', 'x', 'judging')"
        )
        store = VectorStore(conn, FakeEmbedder(dim=8))
        store.write("r-pool", [Chunk(page=1, text="content")])

        # Force a narrow LLM gate so most threads must queue.
        monkeypatch.setattr(nodes_mod, "_judge_sem", threading.Semaphore(2))

        def slow_judge(state, disclosure, store_, llm, conn_, **kw):
            time.sleep(0.05)  # hold the slot so queueing actually happens
            return {"findings": [{"disclosure_id": disclosure.id}]}

        monkeypatch.setattr(nodes_mod, "judge_one_node", slow_judge)

        judge_all_node(
            {"run_id": "r-pool"},
            [_disc(f"2-{i}") for i in range(1, 13)],  # 12 disclosures
            store,
            FakeJudgeLLM(),
            conn,
            max_workers=12,  # 12 threads, but only 2 may work at once
        )

    assert peak <= 3, (
        f"peak concurrent connections was {peak} with a 2-slot LLM semaphore — "
        "queued workers are holding connections they cannot use"
    )
