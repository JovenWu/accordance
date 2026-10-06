"""Tests for the page-coherent sibling-swap step in judge_disclosure.

Scenario
--------
Page 24 of the report has two chunks:
  - chunk_id=1  narrative (in top-k after retrieval)
  - chunk_id=2  table with numbers (NOT in top-k — garbled text, ranks below k)

Page 99 has a third chunk:
  - chunk_id=3  unrelated content (also in top-k, low priority)

With retrieval_page_coherent=True (default):
  - The top-k merged pool is [chunk 1 (p24), chunk 3 (p99)].
  - Pages of top-ranked hits include page 24.
  - retrieve_page_siblings(pages=[24], exclude=[1]) returns chunk 2.
  - chunk 2 is SWAPPED in for the WEAKEST member (chunk 3, the last after sort).
  - Final pool size is unchanged (still 2 items).
  - chunk 2 IS in the final pool; chunk 3 IS NOT.

With retrieval_page_coherent=False:
  - No sibling swap occurs — chunk 2 never appears; chunk 3 stays.
"""

from accordance.judge.core import judge_disclosure
from accordance.kb.schema import Disclosure, RequiredElement
from accordance.llm.adapter import FakeJudgeLLM


def _disclosure() -> Disclosure:
    return Disclosure(
        id="303-3",
        standard="GRI 303",
        title="Water withdrawal",
        category="topic",
        requirement_text="Disclose total water withdrawal.",
        required_elements=[RequiredElement(id="total_vol", desc="Total volume withdrawn")],
        retrieval_queries=["water withdrawal volume"],
        suggested_fix_template="Add water table.",
    )


class _PageSiblingStore:
    """Stub that mimics the minimal VectorStore interface needed by the swap step.

    Exposes retrieve_page_siblings; returns chunk_id=2 when asked for page 24
    (the table sibling).
    """

    def retrieve_page_siblings(
        self, run_id: str, pages: list[int], exclude_ids: list[int], limit: int = 50
    ) -> list[dict]:
        results = []
        if 24 in pages and 2 not in exclude_ids:
            results.append(
                {"chunk_id": 2, "page": 24, "text": "22699 ha total land area", "distance": 0.0}
            )
        return results


def _make_retriever():
    """Returns two chunks: narrative p24 (chunk 1) and unrelated p99 (chunk 3)."""
    def retrieve(query: str, k: int) -> list[dict]:
        return [
            {"chunk_id": 1, "page": 24, "text": "Land use narrative page 24.", "distance": 0.1},
            {"chunk_id": 3, "page": 99, "text": "Some other content page 99.", "distance": 0.5},
        ]
    return retrieve


def test_page_coherent_swaps_sibling_into_pool():
    """With page_coherent=True, the table sibling replaces the weakest member."""
    store = _PageSiblingStore()
    _out, trace = judge_disclosure(
        disclosure=_disclosure(),
        retrieve=_make_retriever(),
        llm=FakeJudgeLLM(),
        k=5,
        per_element=False,
        page_sibling_store=store,
        run_id="run-test",
        page_coherent=True,
    )
    assert 2 in trace.chunk_ids, f"Expected sibling chunk_id=2 in pool; got {trace.chunk_ids}"
    assert 3 not in trace.chunk_ids, f"Chunk 3 should have been displaced; got {trace.chunk_ids}"
    assert len(trace.chunk_ids) == 2, f"Pool size must be constant; got {len(trace.chunk_ids)}"


def test_page_coherent_disabled_leaves_pool_unchanged():
    """With page_coherent=False, no sibling swap — chunk 3 stays, chunk 2 absent."""
    store = _PageSiblingStore()
    _out, trace = judge_disclosure(
        disclosure=_disclosure(),
        retrieve=_make_retriever(),
        llm=FakeJudgeLLM(),
        k=5,
        per_element=False,
        page_sibling_store=store,
        run_id="run-test",
        page_coherent=False,
    )
    assert 2 not in trace.chunk_ids, "Sibling must NOT be pulled in when disabled"
    assert 3 in trace.chunk_ids, "Original weak member must stay when disabled"
    assert len(trace.chunk_ids) == 2


def test_page_coherent_count_unchanged_when_sibling_found():
    """Pool length must never grow: swap is 1-for-1."""
    store = _PageSiblingStore()
    _out, trace = judge_disclosure(
        disclosure=_disclosure(),
        retrieve=_make_retriever(),
        llm=FakeJudgeLLM(),
        k=5,
        per_element=False,
        page_sibling_store=store,
        run_id="run-test",
        page_coherent=True,
    )
    assert len(trace.chunk_ids) == 2


def test_page_coherent_no_op_when_store_is_none():
    """No page_sibling_store → no swap, no error. Existing behavior unchanged."""
    _out, trace = judge_disclosure(
        disclosure=_disclosure(),
        retrieve=_make_retriever(),
        llm=FakeJudgeLLM(),
        k=5,
        per_element=False,
        page_sibling_store=None,
        run_id="run-test",
        page_coherent=True,
    )
    assert set(trace.chunk_ids) == {1, 3}
    assert len(trace.chunk_ids) == 2


class _MultiSiblingStore:
    """Stub returning TWO siblings for pages in a top-k pool of size 6.

    Pool structure (k=6, N_cap = max(1, 6//3) = 2):
      chunk_id=10, page=5,  distance=0.1  (strong — should NOT be displaced)
      chunk_id=11, page=5,  distance=0.2  (strong — should NOT be displaced)
      chunk_id=12, page=5,  distance=0.3  (strong — should NOT be displaced)
      chunk_id=13, page=5,  distance=0.4  (strong — should NOT be displaced)
      chunk_id=20, page=9,  distance=0.8  (weak — should be displaced by sibling)
      chunk_id=21, page=9,  distance=0.9  (weakest — should be displaced by sibling)

    Siblings NOT in pool (from page 5 which has hot narrative chunks):
      chunk_id=30, page=5,  text="table A with 99999 numbers"
      chunk_id=31, page=5,  text="table B with 88888 numbers"

    k=6 → N_cap = max(1, 6//3) = 2, so BOTH siblings fit (2 slots available).
    Both should be swapped in, each into a DISTINCT slot.
    The displaced members must be 20 and 21 (worst scores), NOT 10-13.
    """

    def retrieve_page_siblings(
        self, run_id: str, pages: list[int], exclude_ids: list[int], limit: int = 50
    ) -> list[dict]:
        results = []
        if 5 in pages:
            if 30 not in exclude_ids:
                results.append(
                    {"chunk_id": 30, "page": 5, "text": "table A 99999", "distance": 0.0}
                )
            if 31 not in exclude_ids:
                results.append(
                    {"chunk_id": 31, "page": 5, "text": "table B 88888", "distance": 0.0}
                )
        return results


def _make_multi_retriever():
    """Returns 6 chunks where the last two (20, 21) have the worst (highest) distances."""
    def retrieve(query: str, k: int) -> list[dict]:
        return [
            {"chunk_id": 10, "page": 5, "text": "Strong narrative chunk A.", "distance": 0.1},
            {"chunk_id": 11, "page": 5, "text": "Strong narrative chunk B.", "distance": 0.2},
            {"chunk_id": 12, "page": 5, "text": "Strong narrative chunk C.", "distance": 0.3},
            {"chunk_id": 13, "page": 5, "text": "Strong narrative chunk D.", "distance": 0.4},
            {"chunk_id": 20, "page": 9, "text": "Weak chunk E page 9.", "distance": 0.8},
            {"chunk_id": 21, "page": 9, "text": "Weak chunk F page 9.", "distance": 0.9},
        ]
    return retrieve


def test_multi_sibling_both_land_in_distinct_slots():
    """Two siblings must land in TWO DISTINCT slots; pool size stays constant.

    k=6 → N_cap = max(1, 6//3) = 2 slots available.
    Both siblings (30 and 31) must appear in the final pool, each in its own
    slot — the buggy code wrote `merged[-1]` every iteration, so the second
    sibling overwrote the first's slot and only one survived.
    """
    store = _MultiSiblingStore()
    _out, trace = judge_disclosure(
        disclosure=_disclosure(),
        retrieve=_make_multi_retriever(),
        llm=FakeJudgeLLM(),
        k=6,
        per_element=False,
        page_sibling_store=store,
        run_id="run-test",
        page_coherent=True,
    )
    assert len(trace.chunk_ids) == 6, f"Pool size must stay 6; got {len(trace.chunk_ids)}"
    assert 30 in trace.chunk_ids, f"Sibling 30 must be in pool; got {trace.chunk_ids}"
    assert 31 in trace.chunk_ids, f"Sibling 31 must be in pool; got {trace.chunk_ids}"
    assert 20 not in trace.chunk_ids, f"Weak chunk 20 must be displaced; got {trace.chunk_ids}"
    assert 21 not in trace.chunk_ids, f"Weak chunk 21 must be displaced; got {trace.chunk_ids}"


def test_multi_sibling_high_score_chunk_not_displaced_by_page_order():
    """A higher-page chunk with a GOOD score must NOT be displaced.

    Chunks 10-13 (page=5, distance=0.1-0.4) are strong.  Chunks 20-21
    (page=9, distance=0.8-0.9) are weak. After page-ordered sort the old
    code treated merged[-1] (highest page = chunk 21, page=9) as "weakest",
    which was accidentally correct for the first sibling. But the SECOND
    iteration would overwrite the SAME slot (merged[-1]) with sibling 31,
    leaving sibling 30 lost.

    This test guards the score-based displacement: only the two weakest-BY-
    SCORE members (20, 21) should be displaced; the strong ones (10-13) must
    survive regardless of their position in the sorted pool.
    """
    store = _MultiSiblingStore()
    _out, trace = judge_disclosure(
        disclosure=_disclosure(),
        retrieve=_make_multi_retriever(),
        llm=FakeJudgeLLM(),
        k=6,
        per_element=False,
        page_sibling_store=store,
        run_id="run-test",
        page_coherent=True,
    )
    for cid in (10, 11, 12, 13):
        ids = trace.chunk_ids
        assert cid in ids, f"Strong chunk {cid} must not be displaced; got {ids}"
    assert 30 in trace.chunk_ids, f"Sibling 30 must replace a weak chunk; got {trace.chunk_ids}"
    assert 31 in trace.chunk_ids, f"Sibling 31 must replace a weak chunk; got {trace.chunk_ids}"
