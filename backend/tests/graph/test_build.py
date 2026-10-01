from pathlib import Path

from accordance import db
from accordance.graph.build import build_graph, run_graph
from accordance.indexer.embedder import FakeEmbedder
from accordance.kb.schema import Disclosure, RequiredElement
from accordance.llm.adapter import FakeJudgeLLM

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_report.pdf"


def test_run_graph_processes_one_disclosure_end_to_end(monkeypatch):
    monkeypatch.setenv("RERANK_ENABLED", "false")
    with db.connection() as conn:
        run_id = "r-end2end"
        conn.execute(
            "INSERT INTO reports (id, name) VALUES (%s, %s)",
            ("rep-build-1", "sample_report.pdf"),
        )
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, pdf_sha256, pdf_path, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                run_id,
                "rep-build-1",
                1,
                "initial",
                "sample_report.pdf",
                "sha",
                str(FIXTURE),
                "queued",
            ),
        )

        kb = {
            "303-3": Disclosure(
                id="303-3",
                standard="GRI 303",
                title="Water withdrawal",
                category="topic",
                requirement_text="Total water withdrawal",
                required_elements=[RequiredElement(id="total", desc="total")],
                retrieval_queries=["water"],
                suggested_fix_template="Add a breakdown.",
            )
        }

        run_graph(
            run_id=run_id,
            pdf_path=FIXTURE,
            kb=kb,
            conn=conn,
            embedder=FakeEmbedder(dim=8),
            llm=FakeJudgeLLM(),
        )

        row = conn.execute("SELECT status FROM runs WHERE id=%s", (run_id,)).fetchone()
        assert row["status"] == "completed"
        findings = conn.execute(
            "SELECT disclosure_id FROM findings WHERE run_id=%s", (run_id,)
        ).fetchall()
        assert {f["disclosure_id"] for f in findings} == {"303-3"}


def _kb():
    return {
        "2-1": Disclosure(
            id="2-1",
            standard="GRI 2",
            title="Org",
            category="universal",
            requirement_text="r",
            required_elements=[RequiredElement(id="x", desc="x")],
            retrieval_queries=["q"],
            suggested_fix_template="fix",
        )
    }


def test_full_graph_has_extract_and_index():
    with db.connection() as conn:
        g = build_graph(_kb(), conn, FakeEmbedder(dim=8), FakeJudgeLLM())
        nodes = set(g.get_graph().nodes)
        assert {"extract", "index", "judge", "aggregate"} <= nodes


def test_reuse_index_graph_skips_extract_and_index():
    with db.connection() as conn:
        g = build_graph(_kb(), conn, FakeEmbedder(dim=8), FakeJudgeLLM(), reuse_index=True)
        nodes = set(g.get_graph().nodes)
        assert "judge" in nodes and "aggregate" in nodes
        assert "extract" not in nodes
        assert "index" not in nodes


def test_reuse_index_graph_executes_and_writes_findings(monkeypatch):
    """reuse_index=True: pre-seeded chunks are judged; run reaches 'completed'."""
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("VISION_FALLBACK_ENABLED", "false")
    monkeypatch.setenv("RERANK_ENABLED", "false")

    from accordance.graph.build import run_graph
    from accordance.indexer.chunker import Chunk
    from accordance.indexer.vector_store import VectorStore

    with db.connection() as conn:
        run_id = "r-reuse"
        conn.execute("INSERT INTO reports (id, name) VALUES (%s, %s)", ("rep-reuse", "x.pdf"))
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, "
            "pdf_filename, pdf_sha256, pdf_path, status) "
            "VALUES (%s, %s, 1, 'retry', 'x.pdf', 'sha', 'x', 'queued')",
            (run_id, "rep-reuse"),
        )
        # Pre-seed a chunk (mirrors the chunk-copy that retry/fork performs)
        store = VectorStore(conn, FakeEmbedder(dim=8))
        store.write(run_id, [Chunk(page=1, text="water withdrawal 41 ML total")])

        run_graph(
            run_id=run_id,
            pdf_path=Path("x.pdf"),  # never read — no extract node in reuse_index mode
            kb=_kb(),
            conn=conn,
            embedder=FakeEmbedder(dim=8),
            llm=FakeJudgeLLM(),
            reuse_index=True,
        )

        status = conn.execute("SELECT status FROM runs WHERE id=%s", (run_id,)).fetchone()["status"]
        assert status == "completed"
        findings = conn.execute(
            "SELECT disclosure_id FROM findings WHERE run_id=%s", (run_id,)
        ).fetchall()
        assert {f["disclosure_id"] for f in findings} == {"2-1"}


def test_tag_aware_surfaces_tagged_chunk(monkeypatch):
    """tag_aware=True force-includes a chunk citing the disclosure's GRI tag."""
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("VISION_FALLBACK_ENABLED", "false")
    monkeypatch.setenv("RERANK_ENABLED", "false")
    monkeypatch.setenv("RETRIEVAL_TAG_AWARE", "true")

    import json as _json

    from accordance.graph.build import run_graph
    from accordance.indexer.chunker import Chunk
    from accordance.indexer.vector_store import VectorStore

    with db.connection() as conn:
        run_id = "r-tag"
        conn.execute("INSERT INTO reports (id, name) VALUES (%s, %s)", ("rep-tag", "x.pdf"))
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status) VALUES "
            "(%s, %s, 1, 'retry', 'x.pdf', 'sha', 'x', 'queued')",
            (run_id, "rep-tag"),
        )
        store = VectorStore(conn, FakeEmbedder(dim=8))
        # A chunk that cites the GRI tag for disclosure 2-1, with content that
        # FakeEmbedder won't rank as semantically relevant — only the tag match
        # should surface it.
        store.write(
            run_id,
            [
                Chunk(page=99, text="Appendix data table [[GRI 2-1]] legal name details here"),
                Chunk(page=1, text="unrelated narrative about water and emissions"),
            ],
        )
        run_graph(
            run_id=run_id,
            pdf_path=Path("x.pdf"),
            kb=_kb(),
            conn=conn,
            embedder=FakeEmbedder(dim=8),
            llm=FakeJudgeLLM(),
            reuse_index=True,
        )
        row = conn.execute(
            "SELECT chunk_ids_json, pages_json FROM judge_traces"
            " WHERE run_id=%s AND disclosure_id='2-1'",
            (run_id,),
        ).fetchone()
        assert row is not None
        # the tagged chunk's page was surfaced to the judge
        assert 99 in _json.loads(row["pages_json"])


def test_judge_node_runs_disclosures_concurrently(monkeypatch):
    """The judge node parallelizes per-disclosure calls — a serial fan-out fails this.

    With N disclosures whose judge LLM each sleeps DELAY, serial execution takes
    >= N*DELAY; a thread pool of N workers takes ~DELAY. The assertion sits well
    below the serial floor so it only passes when judging is concurrent.
    """
    import time

    import accordance.graph.nodes as nodes_mod
    from accordance.graph.build import run_graph
    from accordance.indexer.chunker import Chunk
    from accordance.indexer.vector_store import VectorStore
    from accordance.llm.adapter import FakeJudgeLLM

    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("VISION_FALLBACK_ENABLED", "false")
    monkeypatch.setenv("RERANK_ENABLED", "false")
    monkeypatch.setenv("JUDGE_CONCURRENCY", "8")
    # The judge semaphore is a lazily-cached module global; reset it so it
    # re-reads the patched JUDGE_CONCURRENCY instead of a prior test's value.
    monkeypatch.setattr(nodes_mod, "_judge_sem", None, raising=False)

    DELAY = 0.3
    N = 8

    class SleepyJudgeLLM(FakeJudgeLLM):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            time.sleep(DELAY)
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def d(i):
        return Disclosure(
            id=f"2-{i}",
            standard="GRI 2",
            title=f"2-{i}",
            category="universal",
            requirement_text="r",
            required_elements=[RequiredElement(id="x", desc="x")],
            retrieval_queries=["q"],
            suggested_fix_template="fix",
        )

    kb = {f"2-{i}": d(i) for i in range(N)}

    with db.connection() as conn:
        conn.execute("INSERT INTO reports (id, name) VALUES ('rep-cc', 'x.pdf')")
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status) VALUES "
            "('r-cc', 'rep-cc', 1, 'initial', 'x.pdf', 'sha', 'x', 'queued')"
        )
        VectorStore(conn, FakeEmbedder(dim=8)).write("r-cc", [Chunk(page=1, text="content")])

        t0 = time.monotonic()
        run_graph(
            run_id="r-cc",
            pdf_path=Path("x.pdf"),
            kb=kb,
            conn=conn,
            embedder=FakeEmbedder(dim=8),
            llm=SleepyJudgeLLM(),
            reuse_index=True,
        )
        wall = time.monotonic() - t0

        judged = {
            r["disclosure_id"]
            for r in conn.execute("SELECT disclosure_id FROM findings WHERE run_id='r-cc'")
        }
        assert judged == set(kb)  # all disclosures judged
        assert wall < N * DELAY * 0.5, (
            f"judging looks serial: {wall:.2f}s for {N} disclosures x {DELAY}s "
            f"(serial floor {N * DELAY:.1f}s)"
        )
