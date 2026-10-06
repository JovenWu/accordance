from accordance.judge.core import JudgeTrace, judge_disclosure
from accordance.kb.schema import Disclosure, RequiredElement
from accordance.llm.adapter import FakeJudgeLLM


def fake_retriever(query: str, k: int) -> list[dict]:
    return [{"chunk_id": 1, "page": 1, "text": "Sample excerpt.", "distance": 0.1}]


def test_judge_returns_output_with_fake_llm():
    disclosure = Disclosure(
        id="303-3",
        standard="GRI 303",
        title="Water withdrawal",
        category="topic",
        requirement_text="Total withdrawal...",
        required_elements=[RequiredElement(id="x", desc="x")],
        retrieval_queries=["water withdrawal"],
        suggested_fix_template="add table.",
    )
    out, trace = judge_disclosure(
        disclosure=disclosure,
        retrieve=fake_retriever,
        llm=FakeJudgeLLM(),
        k=5,
    )
    assert out.status in ("covered", "partial", "missing")
    assert out.note
    assert isinstance(trace, JudgeTrace)
    assert trace.chunk_ids == [1]
    assert trace.pages == [1]
    assert trace.prompt_hash
    assert trace.parse_path in ("structured", "fallback")
    assert trace.rejudged is False


class _ReverseReranker:
    """Reverses the candidate order — proves rerank order is applied."""

    def rerank(self, query, passages, top_n):
        return list(reversed(range(len(passages))))[:top_n]


def _retriever_three(query: str, k: int):
    return [
        {"chunk_id": 1, "page": 5, "text": "alpha", "distance": 0.1},
        {"chunk_id": 2, "page": 4, "text": "beta", "distance": 0.2},
        {"chunk_id": 3, "page": 6, "text": "gamma", "distance": 0.3},
    ]


def _disclosure_one_query():
    return Disclosure(
        id="2-1", standard="GRI 2", title="Org", category="universal",
        requirement_text="Report org details.",
        required_elements=[RequiredElement(id="x", desc="x")],
        retrieval_queries=["org details"], suggested_fix_template="fix",
    )


def test_judge_uses_reranker_order():
    _out, trace = judge_disclosure(
        disclosure=_disclosure_one_query(), retrieve=_retriever_three,
        llm=FakeJudgeLLM(), k=5, per_element=False, reranker=_ReverseReranker(),
    )
    assert trace.chunk_ids == [3, 2, 1]


def test_judge_pagesorts_without_reranker():
    _out, trace = judge_disclosure(
        disclosure=_disclosure_one_query(), retrieve=_retriever_three,
        llm=FakeJudgeLLM(), k=5, per_element=False, reranker=None,
    )
    assert trace.chunk_ids == [2, 1, 3]


def test_judge_reranker_respects_top_n():
    _out, trace = judge_disclosure(
        disclosure=_disclosure_one_query(), retrieve=_retriever_three,
        llm=FakeJudgeLLM(), k=5, per_element=False,
        reranker=_ReverseReranker(), rerank_top_n=2,
    )
    assert trace.chunk_ids == [3, 2]


class _OOBReranker:
    """Returns out-of-range and duplicate indices — judge must filter them."""

    def rerank(self, query, passages, top_n):
        return [2, 999, 1, -1, 2]


def test_judge_reranker_ignores_invalid_indices():
    _out, trace = judge_disclosure(
        disclosure=_disclosure_one_query(), retrieve=_retriever_three,
        llm=FakeJudgeLLM(), k=5, per_element=False, reranker=_OOBReranker(),
    )
    assert trace.chunk_ids == [3, 2]


def test_system_message_cache_block_when_enabled():
    from accordance.judge.core import _build_system_message

    m = _build_system_message(cache=True)
    assert isinstance(m.content, list)
    assert m.content[0]["type"] == "text"
    assert m.content[0]["cache_control"] == {"type": "ephemeral"}


def test_system_message_plain_when_disabled():
    from accordance.judge.core import _build_system_message

    m = _build_system_message(cache=False)
    assert isinstance(m.content, str)


def test_judge_force_includes_tag_chunks():
    def _tag_retrieve(limit):
        return [
            {"chunk_id": 99, "page": 183, "text": "[[GRI 2-1]] org data table", "distance": 0.0}
        ]
    _out, trace = judge_disclosure(
        disclosure=_disclosure_one_query(), retrieve=_retriever_three,
        llm=FakeJudgeLLM(), k=5, per_element=False, reranker=_ReverseReranker(),
        tag_retrieve=_tag_retrieve,
    )
    assert 99 in trace.chunk_ids
    assert trace.chunk_ids[0] == 99
