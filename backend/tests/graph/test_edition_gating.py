from pathlib import Path

from accordance import db
from accordance.graph.build import run_graph
from accordance.indexer.chunker import Chunk
from accordance.indexer.embedder import FakeEmbedder
from accordance.indexer.vector_store import VectorStore
from accordance.kb.schema import Disclosure, RequiredElement
from accordance.llm.adapter import FakeJudgeLLM


def _d(did: str, *, status: str = "current", **extra) -> Disclosure:
    return Disclosure(
        id=did,
        standard="GRI X",
        title=did,
        category="topic",
        requirement_text="r",
        required_elements=[RequiredElement(id="x", desc="x")],
        retrieval_queries=["q"],
        suggested_fix_template="fix",
        status=status,
        **extra,
    )


def _mixed_kb() -> dict[str, Disclosure]:
    return {
        "cur": _d("cur"),
        "old": _d("old", status="superseded", effective_until="2025-12-31"),
        "new": _d("new", status="upcoming", effective_date="2027-01-01"),
    }


def _setup(conn, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "fake:fake")
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("VISION_FALLBACK_ENABLED", "false")
    monkeypatch.setenv("RERANK_ENABLED", "false")
    conn.execute("INSERT INTO reports (id, name) VALUES ('rep', 'x.pdf')")
    conn.execute(
        "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
        "pdf_sha256, pdf_path, status) VALUES "
        "('r-ed', 'rep', 1, 'initial', 'x.pdf', 'sha', 'x', 'queued')"
    )
    VectorStore(conn, FakeEmbedder(dim=8)).write("r-ed", [Chunk(page=1, text="content")])


def _judged(conn) -> set[str]:
    return {
        r["disclosure_id"]
        for r in conn.execute("SELECT disclosure_id FROM findings WHERE run_id='r-ed'")
    }


def test_default_path_judges_only_current_editions(monkeypatch):
    """With no explicit selection, the judge default path must skip superseded
    and upcoming editions so a report isn't graded against a withdrawn AND a
    replacement edition of the same standard."""
    with db.connection() as conn:
        _setup(conn, monkeypatch)
        run_graph(
            run_id="r-ed",
            pdf_path=Path("x.pdf"),
            kb=_mixed_kb(),
            conn=conn,
            embedder=FakeEmbedder(dim=8),
            llm=FakeJudgeLLM(),
            reuse_index=True,
        )
        assert _judged(conn) == {"cur"}


def test_explicit_selection_bypasses_edition_gate(monkeypatch):
    """An explicit disclosure_ids selection is an opt-in — it must still judge a
    superseded/upcoming edition the user deliberately chose."""
    with db.connection() as conn:
        _setup(conn, monkeypatch)
        run_graph(
            run_id="r-ed",
            pdf_path=Path("x.pdf"),
            kb=_mixed_kb(),
            conn=conn,
            embedder=FakeEmbedder(dim=8),
            llm=FakeJudgeLLM(),
            reuse_index=True,
            disclosure_ids=["old"],
        )
        assert _judged(conn) == {"old"}
