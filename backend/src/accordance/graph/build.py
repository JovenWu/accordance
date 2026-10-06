import logging
from pathlib import Path

import psycopg
from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from accordance.graph.nodes import aggregate_node, extract_node, index_node, judge_all_node
from accordance.graph.state import GraphState
from accordance.indexer.embedder import Embedder
from accordance.indexer.vector_store import VectorStore
from accordance.kb.loader import applicable_disclosures
from accordance.kb.schema import Disclosure

logger = logging.getLogger(__name__)


def _set_stage(conn: psycopg.Connection, run_id: str, status: str) -> None:
    """Advance the run's visible pipeline stage as each node starts.

    The status column is what the UI's stepper animates from — without these
    writes a run sits at 'queued' until 'completed' and Extract/Index/Judge
    never light up. Guarded to in-flight statuses: a run flipped to
    'cancelled'/'failed' by stop_run or restart reconciliation mid-stage must
    not be resurrected by the next node's write. Best-effort — a stage write
    must never fail the run itself.
    """
    try:
        cur = conn.execute(
            "UPDATE runs SET status=%s WHERE id=%s "
            "AND status IN ('queued','extracting','indexing','judging')",
            (status, run_id),
        )
        if cur.rowcount > 0:
            try:
                from accordance.api.events import bus

                bus.publish(run_id, {"type": "stage", "status": status})
            except Exception:
                pass
    except Exception:
        logger.warning("stage update to %r failed for run %s", status, run_id, exc_info=True)


def build_graph(
    kb: dict[str, Disclosure],
    conn: psycopg.Connection,
    embedder: Embedder,
    llm: BaseChatModel,
    retrieval_mode: str = "hybrid",
    reuse_index: bool = False,
    reranker=None,
    rerank_top_n: int = 15,
    cache_system: bool = False,
    tag_aware: bool = False,
    tag_limit: int = 5,
    disclosure_ids: list[str] | None = None,
    judge_concurrency: int = 12,
):
    store = VectorStore(conn, embedder, mode=retrieval_mode)
    if disclosure_ids:
        wanted = set(disclosure_ids)
        disclosures = [d for d in kb.values() if d.id in wanted]
    else:
        disclosures = list(applicable_disclosures(kb).values())

    def _extract(state):
        _set_stage(conn, state["run_id"], "extracting")
        return extract_node(state)

    def _index(state):
        _set_stage(conn, state["run_id"], "indexing")
        return index_node(state, store, conn)

    def _judge(state):
        _set_stage(conn, state["run_id"], "judging")
        return judge_all_node(
            state, disclosures, store, llm, conn,
            reranker=reranker, rerank_top_n=rerank_top_n, cache_system=cache_system,
            tag_aware=tag_aware, tag_limit=tag_limit, max_workers=judge_concurrency,
        )

    def _aggregate(state):
        return aggregate_node(state, conn, expected_disclosures=disclosures)

    g = StateGraph(GraphState)
    g.add_node("judge", _judge)
    g.add_node("aggregate", _aggregate)

    if reuse_index:
        g.add_edge(START, "judge")
    else:
        g.add_node("extract", _extract)
        g.add_node("index", _index)
        g.add_edge(START, "extract")
        g.add_edge("extract", "index")
        g.add_edge("index", "judge")

    g.add_edge("judge", "aggregate")
    g.add_edge("aggregate", END)
    return g.compile()


def run_graph(
    run_id: str,
    pdf_path: Path,
    kb: dict[str, Disclosure],
    conn: psycopg.Connection,
    embedder: Embedder,
    llm: BaseChatModel,
    retrieval_mode: str = "hybrid",
    reuse_index: bool = False,
    disclosure_ids: list[str] | None = None,
) -> None:
    from accordance.config import get_settings
    from accordance.indexer.reranker import build_reranker

    s = get_settings()
    reranker = build_reranker(s.rerank_enabled, s.rerank_model, s.rerank_threads)
    graph = build_graph(
        kb, conn, embedder, llm,
        retrieval_mode=retrieval_mode, reuse_index=reuse_index,
        reranker=reranker, rerank_top_n=s.rerank_top_n,
        cache_system=s.prompt_cache_enabled,
        tag_aware=s.retrieval_tag_aware, tag_limit=s.retrieval_tag_limit,
        disclosure_ids=disclosure_ids,
        judge_concurrency=s.judge_concurrency,
    )
    graph.invoke({"run_id": run_id, "pdf_path": str(pdf_path)})
