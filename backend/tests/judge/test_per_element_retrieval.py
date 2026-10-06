"""Per-element retrieval expansion + flag toggle."""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from accordance.judge.core import judge_disclosure, judge_disclosure_with_rejudge
from accordance.kb.schema import Disclosure, RequiredElement


class _CannedLLM(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "canned"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.outputs import ChatGeneration, ChatResult

        content = (
            '{"status":"covered","elements":[{"id":"a","status":"found","page":1}],'
            '"note":"ok","evidence_excerpt":"e","evidence_page":1,'
            '"needs_vision_fallback":false}'
        )
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=content))]
        )

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _retriever(_q, _k):
    return [{"chunk_id": 1, "page": 1, "text": "x", "distance": 0.1}]


def _disclosure() -> Disclosure:
    return Disclosure(
        id="2-1",
        standard="GRI 2",
        title="Org details",
        category="universal",
        requirement_text="Report org details.",
        required_elements=[
            RequiredElement(id="legal_name", desc="Legal name of the organization"),
            RequiredElement(
                id="hq_location", desc="City and country of headquarters"
            ),
        ],
        retrieval_queries=["company legal name ownership"],
        suggested_fix_template="add about page.",
    )


def test_per_element_expands_queries():
    """First-pass queries include retrieval_queries UNION element descriptions."""
    _, trace = judge_disclosure(_disclosure(), _retriever, _CannedLLM(), per_element=True)
    assert trace.queries_used == [
        "company legal name ownership",
        "Legal name of the organization",
        "City and country of headquarters",
    ]


def test_per_element_disabled_falls_back_to_retrieval_queries_only():
    _, trace = judge_disclosure(_disclosure(), _retriever, _CannedLLM(), per_element=False)
    assert trace.queries_used == ["company legal name ownership"]


def test_override_queries_wins_over_per_element_flag():
    """When override_queries is set (e.g., during re-judge), it takes priority
    regardless of the per_element flag — re-judge must control its own scope."""
    _, trace = judge_disclosure(
        _disclosure(),
        _retriever,
        _CannedLLM(),
        per_element=True,
        override_queries=["only this"],
    )
    assert trace.queries_used == ["only this"]


def test_with_rejudge_first_pass_uses_per_element_expansion():
    _, traces = judge_disclosure_with_rejudge(
        _disclosure(), _retriever, _CannedLLM(), per_element=True
    )
    assert len(traces) == 1
    assert "Legal name of the organization" in traces[0].queries_used
