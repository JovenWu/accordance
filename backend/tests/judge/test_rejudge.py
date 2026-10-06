"""Tests for judge_disclosure_with_rejudge: only re-judge on 'missing'."""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from accordance.judge.core import judge_disclosure_with_rejudge
from accordance.kb.schema import Disclosure, RequiredElement


class _ScriptedLLM(BaseChatModel):
    """Returns canned JudgeOutput JSON in order, one per .invoke()."""

    def __init__(self, responses: list[str]):
        super().__init__()
        object.__setattr__(self, "_responses", list(responses))
        object.__setattr__(self, "_idx", 0)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.outputs import ChatGeneration, ChatResult

        i = self._idx
        object.__setattr__(self, "_idx", i + 1)
        content = self._responses[i] if i < len(self._responses) else self._responses[-1]
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=content))]
        )

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _retriever(_q, _k):
    return [{"chunk_id": 1, "page": 1, "text": "x", "distance": 0.1}]


def _disclosure() -> Disclosure:
    return Disclosure(
        id="305-1",
        standard="GRI 305",
        title="Scope 1",
        category="topic",
        requirement_text="Direct GHG emissions",
        required_elements=[
            RequiredElement(id="scope_1", desc="Scope 1 emissions in tCO2e"),
            RequiredElement(id="gases", desc="List of gases included"),
        ],
        retrieval_queries=["scope 1 emissions"],
        suggested_fix_template="add table.",
    )


_MISSING_JSON = (
    '{"status":"missing","elements":[],"note":"none found",'
    '"evidence_excerpt":null,"evidence_page":null,"needs_vision_fallback":false}'
)
_COVERED_JSON = (
    '{"status":"covered","elements":[{"id":"scope_1","status":"found","page":1},'
    '{"id":"gases","status":"found","page":1}],"note":"all found",'
    '"evidence_excerpt":"e","evidence_page":1,"needs_vision_fallback":false}'
)
_PARTIAL_JSON = (
    '{"status":"partial","elements":[{"id":"scope_1","status":"found","page":1}],'
    '"note":"some","evidence_excerpt":"e","evidence_page":1,'
    '"needs_vision_fallback":false}'
)


def test_no_rejudge_when_first_pass_covered():
    llm = _ScriptedLLM([_COVERED_JSON, _MISSING_JSON])
    out, traces = judge_disclosure_with_rejudge(_disclosure(), _retriever, llm)
    assert out.status == "covered"
    assert len(traces) == 1
    assert traces[0].rejudged is False


def test_no_rejudge_when_first_pass_partial():
    llm = _ScriptedLLM([_PARTIAL_JSON, _MISSING_JSON])
    out, traces = judge_disclosure_with_rejudge(_disclosure(), _retriever, llm)
    assert out.status == "partial"
    assert len(traces) == 1


def test_rejudge_overrides_when_second_pass_finds_evidence():
    """First pass missing, second pass covered → final = covered, 2 traces."""
    llm = _ScriptedLLM([_MISSING_JSON, _COVERED_JSON])
    out, traces = judge_disclosure_with_rejudge(_disclosure(), _retriever, llm)
    assert out.status == "covered"
    assert len(traces) == 2
    assert traces[0].rejudged is False
    assert traces[1].rejudged is True
    assert traces[1].queries_used == [
        "Scope 1 emissions in tCO2e",
        "List of gases included",
    ]


def test_rejudge_keeps_first_verdict_when_second_pass_also_missing():
    """Both passes missing → final = missing (first), 2 traces persisted."""
    llm = _ScriptedLLM([_MISSING_JSON, _MISSING_JSON])
    out, traces = judge_disclosure_with_rejudge(_disclosure(), _retriever, llm)
    assert out.status == "missing"
    assert len(traces) == 2


def test_rejudge_disabled_by_flag():
    """rejudge_on_missing=False → only one pass even when first is missing."""
    llm = _ScriptedLLM([_MISSING_JSON, _COVERED_JSON])
    out, traces = judge_disclosure_with_rejudge(
        _disclosure(), _retriever, llm, rejudge_on_missing=False
    )
    assert out.status == "missing"
    assert len(traces) == 1


def test_trace_carries_prompt_hash_and_model_id():
    llm = _ScriptedLLM([_COVERED_JSON])
    _, traces = judge_disclosure_with_rejudge(_disclosure(), _retriever, llm)
    assert traces[0].prompt_hash
    assert len(traces[0].prompt_hash) == 16
    assert traces[0].model_id == "_ScriptedLLM"
