"""Pure-function tests for the evidence verifier."""

import pytest

from accordance.judge.verify import _normalize, verify_excerpt


def _chunk(text: str) -> dict:
    return {"chunk_id": 1, "page": 1, "text": text, "distance": 0.1}


def test_normalize_lowercases_and_collapses_whitespace():
    assert _normalize("Hello   World") == "hello world"
    assert _normalize("\n  TEXT\t\nhere\n") == "text here"


def test_normalize_strips_edge_punctuation():
    assert _normalize('"hello world."') == "hello world"
    assert _normalize("...mid sentence...") == "mid sentence"


def test_empty_excerpt_is_verified():
    assert verify_excerpt(None, []) is True
    assert verify_excerpt("", [_chunk("anything")]) is True
    assert verify_excerpt("   \n  ", [_chunk("anything")]) is True


def test_exact_substring_match_verified():
    chunks = [_chunk("Our Scope 1 emissions for FY2024 totaled 12,450 tCO2e.")]
    assert verify_excerpt("Scope 1 emissions for FY2024 totaled 12,450 tCO2e", chunks)


def test_case_and_whitespace_differences_ok():
    chunks = [_chunk("Acme  Industries  PTE  LTD  is  Singapore-based.")]
    assert verify_excerpt("acme industries pte ltd is singapore-based", chunks)


def test_excerpt_with_smart_quotes_and_trailing_period():
    chunks = [_chunk("We operate in five countries: SG, MY, ID, VN, TH.")]
    assert verify_excerpt(
        '"We operate in five countries: SG, MY, ID, VN, TH."', chunks
    )


def test_searches_all_chunks():
    """Match against any chunk in the list, not just the first."""
    chunks = [
        _chunk("Unrelated content on page one."),
        _chunk("Headquarters at 1 Marina Boulevard, Singapore."),
        _chunk("Also unrelated."),
    ]
    assert verify_excerpt("1 Marina Boulevard, Singapore", chunks)


def test_made_up_quote_not_verified():
    chunks = [_chunk("Our Scope 1 emissions for FY2024 totaled 12,450 tCO2e.")]
    assert not verify_excerpt("Scope 1 emissions totaled 999,999 tCO2e", chunks)


def test_excerpt_from_a_chunk_we_didnt_retrieve():
    """Quotes that are 'real' for the report but not in our retrieved chunks
    should NOT verify — we can only check what the LLM was actually shown."""
    chunks = [_chunk("Greenhouse gas emissions section header only.")]
    assert not verify_excerpt(
        "Scope 1 emissions for FY2024 totaled 12,450 tCO2e", chunks
    )


def test_empty_chunks_list_returns_false_for_real_excerpt():
    assert not verify_excerpt("anything substantive here", [])


def test_paraphrased_excerpt_with_high_overlap_verified():
    """LLM dropped a stray adjective; >=70% of content words still match."""
    chunks = [
        _chunk(
            "Our Scope 1 emissions for the fiscal year 2024 totaled "
            "approximately 12,450 metric tonnes of CO2 equivalent."
        )
    ]
    assert verify_excerpt(
        "Scope 1 emissions fiscal year 2024 totaled 12,450 metric tonnes CO2",
        chunks,
    )


def test_low_overlap_paraphrase_rejected():
    chunks = [_chunk("Our Scope 1 emissions for FY2024 totaled 12,450 tCO2e.")]
    assert not verify_excerpt(
        "Our water withdrawal across all sites was 41 megaliters", chunks
    )


@pytest.fixture
def _judge_imports():
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage

    from accordance.judge.core import judge_disclosure
    from accordance.kb.schema import Disclosure, RequiredElement

    class _CannedLLM(BaseChatModel):
        def __init__(self, content: str):
            super().__init__()
            object.__setattr__(self, "_content", content)

        @property
        def _llm_type(self) -> str:
            return "canned"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            from langchain_core.outputs import ChatGeneration, ChatResult

            return ChatResult(
                generations=[
                    ChatGeneration(message=AIMessage(content=self._content))
                ]
            )

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    return judge_disclosure, _CannedLLM, Disclosure, RequiredElement


def test_hallucinated_excerpt_is_cleared_in_output(_judge_imports):
    judge_disclosure, _CannedLLM, Disclosure, RequiredElement = _judge_imports

    fabricated = (
        '{"status":"covered","elements":[{"id":"x","status":"found","page":1}],'
        '"note":"ok","evidence_excerpt":"This quote does not exist anywhere",'
        '"evidence_page":1,"needs_vision_fallback":false}'
    )

    def retriever(_q, _k):
        return [
            {
                "chunk_id": 1,
                "page": 1,
                "text": "Completely unrelated chunk content.",
                "distance": 0.1,
            }
        ]

    d = Disclosure(
        id="x",
        standard="GRI",
        title="x",
        category="universal",
        requirement_text="x",
        required_elements=[RequiredElement(id="x", desc="x")],
        retrieval_queries=["x"],
        suggested_fix_template="x",
    )
    out, trace = judge_disclosure(d, retriever, _CannedLLM(fabricated))
    assert out.status.value == "covered"
    assert out.note == "ok"
    assert out.evidence_excerpt is None
    assert out.evidence_page is None
    assert trace.evidence_verified is False
    assert trace.original_evidence_excerpt == "This quote does not exist anywhere"


def test_genuine_excerpt_passes_through(_judge_imports):
    judge_disclosure, _CannedLLM, Disclosure, RequiredElement = _judge_imports

    real_chunk = "Acme reported Scope 1 emissions of 12,450 tCO2e in FY2024."
    canned = (
        '{"status":"covered","elements":[{"id":"x","status":"found","page":1}],'
        '"note":"ok","evidence_excerpt":"Acme reported Scope 1 emissions of 12,450 tCO2e",'
        '"evidence_page":1,"needs_vision_fallback":false}'
    )

    def retriever(_q, _k):
        return [{"chunk_id": 1, "page": 1, "text": real_chunk, "distance": 0.1}]

    d = Disclosure(
        id="x",
        standard="GRI",
        title="x",
        category="universal",
        requirement_text="x",
        required_elements=[RequiredElement(id="x", desc="x")],
        retrieval_queries=["x"],
        suggested_fix_template="x",
    )
    out, trace = judge_disclosure(d, retriever, _CannedLLM(canned))
    assert out.evidence_excerpt == "Acme reported Scope 1 emissions of 12,450 tCO2e"
    assert out.evidence_page == 1
    assert trace.evidence_verified is True
    assert trace.original_evidence_excerpt == out.evidence_excerpt
