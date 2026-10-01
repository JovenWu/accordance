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


def build_graph(
    kb: dict[str, Disclosure],
    conn: psycopg.Connection,
    embedder: Embedder,
    llm: BaseChatModel,
    retrieval_mode: str = "hybrid",
    reuse_index: bool = False,
    reranker=None,            # Reranker | None — injected by run_graph
    rerank_top_n: int = 15,
    cache_system: bool = False,
    tag_aware: bool = False,
    tag_limit: int = 5,
    disclosure_ids: list[str] | None = None,
    judge_concurrency: int = 12,
):
    store = VectorStore(conn, embedder, mode=retrieval_mode)
    # None / empty → all disclosures (back-compat). Otherwise judge only the
    # requested ids, preserving KB order and skipping ids not in the KB.
    if disclosure_ids:
        wanted = set(disclosure_ids)
        disclosures = [d for d in kb.values() if d.id in wanted]
    else:
        # Default (no explicit selection): judge only the in-force editions, so a
        # report is never graded against BOTH a withdrawn and its replacement
        # edition of the same standard. An explicit disclosure_ids selection above
        # is an opt-in and deliberately bypasses this gate.
        disclosures = list(applicable_disclosures(kb).values())

    def _extract(state):
        return extract_node(state)

    def _index(state):
        return index_node(state, store, conn)

    # Single node that judges all disclosures CONCURRENTLY (thread pool). We do
    # NOT use a LangGraph Send fan-out: the synchronous graph.invoke() runs
    # fanned-out branches serially, which made a full run take ~N sequential LLM
    # round-trips (the "queue is so long" symptom). judge_all_node parallelizes
    # the per-disclosure calls; the global judge semaphore still caps LLM
    # concurrency across simultaneous runs.
    def _judge(state):
        return judge_all_node(
            state, disclosures, store, llm, conn,
            reranker=reranker, rerank_top_n=rerank_top_n, cache_system=cache_system,
            tag_aware=tag_aware, tag_limit=tag_limit, max_workers=judge_concurrency,
        )

    def _aggregate(state):
        # Pass the set we attempted to judge so aggregate_node can verify every
        # one persisted a finding before marking the run 'completed' (a write
        # failure must never silently drop a disclosure).
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
