"""The disclosure `status` enum must be enforced by the PROVIDER, not just
validated after the fact.

Three disclosures in a real 150-disclosure run failed because the model
returned status="found" — the ELEMENT vocabulary. Both fields are named
`status`, their enums overlap on partial/missing, and the prompt primes
"found" 22 times vs "covered" 9 (the roll-up rule literally reads
"covered = every required element is found"). LangChain's default
`function_calling` method does not constrain generation, so the bad value is
only caught client-side after the call is paid for.

`method="json_schema", strict=True` makes the provider constrain decoding, so
"found" is ungeneratable at the top level. It touches no prompt text, so
PROMPT_HASH — and eval comparability — is unchanged.
"""

from typing import ClassVar

from accordance.judge.core import judge_disclosure
from accordance.judge.output_schema import JudgeOutput
from accordance.kb.schema import Disclosure, RequiredElement
from accordance.llm.adapter import FakeJudgeLLM

_D = Disclosure(
    id="2-1", standard="GRI 2", title="t", category="universal",
    requirement_text="r", required_elements=[RequiredElement(id="x", desc="x")],
    retrieval_queries=["q"], suggested_fix_template="f",
)


class _RecordingLLM(FakeJudgeLLM):
    """Captures how with_structured_output was configured."""

    calls: ClassVar[list] = []

    def with_structured_output(self, schema, **kwargs):
        type(self).calls.append(kwargs)
        return super().with_structured_output(schema)


def _retrieve(q, k):
    return [{"chunk_id": 1, "page": 1, "text": "some text", "distance": 0.1}]


def test_structured_output_requests_provider_enforced_schema():
    _RecordingLLM.calls = []
    judge_disclosure(_D, _retrieve, _RecordingLLM(), structured_method="json_schema")
    assert _RecordingLLM.calls, "with_structured_output was never called"
    kw = _RecordingLLM.calls[0]
    assert kw.get("method") == "json_schema"
    assert kw.get("strict") is True


def test_function_calling_mode_sends_no_schema_kwargs():
    """Escape hatch for proxies that reject json_schema: without it, every
    disclosure would burn a failed call plus a fallback call."""
    _RecordingLLM.calls = []
    judge_disclosure(_D, _retrieve, _RecordingLLM(), structured_method="function_calling")
    assert _RecordingLLM.calls[0] == {}


def test_json_schema_is_the_default():
    """Production runs OpenAI directly, which supports strict json_schema, so
    the default must need no configuration there."""
    _RecordingLLM.calls = []
    judge_disclosure(_D, _retrieve, _RecordingLLM())
    assert _RecordingLLM.calls[0].get("method") == "json_schema"


def test_status_enum_rejects_the_element_vocabulary():
    """Regression guard for the actual failure: status='found'."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        JudgeOutput.model_validate({"status": "found", "elements": [], "note": "n"})
