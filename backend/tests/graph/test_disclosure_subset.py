from pathlib import Path

from accordance import db
from accordance.graph.build import run_graph
from accordance.indexer.chunker import Chunk
from accordance.indexer.embedder import FakeEmbedder
from accordance.indexer.vector_store import VectorStore
from accordance.kb.schema import Disclosure, RequiredElement
from accordance.llm.adapter import FakeJudgeLLM


def _kb():
    def d(i):
        return Disclosure(
            id=i,
            standard="GRI 2",
            title=i,
            category="universal",
            requirement_text="r",
            required_elements=[RequiredElement(id="x", desc="x")],
            retrieval_queries=["q"],
            suggested_fix_template="fix",
        )

    return {"2-1": d("2-1"), "2-2": d("2-2"), "2-3": d("2-3")}


def test_run_graph_only_judges_selected_disclosures(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("VISION_FALLBACK_ENABLED", "false")
    monkeypatch.setenv("RERANK_ENABLED", "false")

    with db.connection() as conn:
        conn.execute("INSERT INTO reports (id, name) VALUES ('rep', 'x.pdf')")
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status) VALUES "
            "('r-sub', 'rep', 1, 'initial', 'x.pdf', 'sha', 'x', 'queued')"
        )
        store = VectorStore(conn, FakeEmbedder(dim=8))
        store.write("r-sub", [Chunk(page=1, text="some content")])

        run_graph(
            run_id="r-sub",
            pdf_path=Path("x.pdf"),
            kb=_kb(),
            conn=conn,
            embedder=FakeEmbedder(dim=8),
            llm=FakeJudgeLLM(),
            reuse_index=True,
            disclosure_ids=["2-2"],
        )

        judged = {
            r["disclosure_id"]
            for r in conn.execute("SELECT disclosure_id FROM findings WHERE run_id='r-sub'")
        }
        assert judged == {"2-2"}
