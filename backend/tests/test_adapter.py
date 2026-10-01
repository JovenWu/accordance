"""Tests for accordance.llm.adapter.build_llm.

Constructing ChatOpenAI does NOT hit the network, so these are safe offline.
"""
from langchain_core.language_models import BaseChatModel

from accordance.llm.adapter import build_llm


def test_build_llm_default_max_retries():
    """Default max_retries is 2 (bounded, not the old hardcoded 5)."""
    m = build_llm("openai:gpt-4o-mini", api_key="sk-test")
    assert m.max_retries == 2


def test_build_llm_custom_max_retries():
    """Caller can override max_retries."""
    m = build_llm("openai:gpt-4o-mini", api_key="sk-test", max_retries=3)
    assert m.max_retries == 3


def test_build_llm_timeout_forwarded():
    """timeout kwarg is forwarded to the underlying model as request_timeout."""
    m = build_llm("openai:gpt-4o-mini", api_key="sk-test", max_retries=3, timeout=42)
    # ChatOpenAI stores the timeout as request_timeout (not .timeout)
    assert m.request_timeout == 42


def test_build_llm_default_timeout():
    """Default timeout is 60.0 seconds."""
    m = build_llm("openai:gpt-4o-mini", api_key="sk-test")
    assert m.request_timeout == 60.0


def test_build_llm_fake_prefix_returns_fake_llm():
    """fake: prefix still returns FakeJudgeLLM without touching the adapter kwargs."""
    from accordance.llm.adapter import FakeJudgeLLM

    m = build_llm("fake:fake")
    assert isinstance(m, FakeJudgeLLM)


# ── reasoning effort ─────────────────────────────────────────────────
# Reasoning tokens bill as OUTPUT, so effort is a direct cost/latency lever.
# Measured on gpt-5.6-luna: none=206 out tok, medium=417, high=729 for the
# same judge prompt. Supported values vary BY MODEL (luna accepts
# none/low/medium/high/xhigh/max but rejects 'minimal'), so the value is
# passed through unvalidated and the provider rejects a bad one.


def test_build_llm_forwards_reasoning_effort():
    m = build_llm("openai:gpt-4o-mini", api_key="sk-test", reasoning_effort="medium")
    assert m.reasoning_effort == "medium"


def test_build_llm_omits_reasoning_effort_by_default():
    """Unset MUST mean 'send no reasoning_effort at all'.

    Non-reasoning models and OpenAI-compatible proxies 400 on the parameter,
    so defaulting to any concrete value would break every existing deployment.
    """
    m = build_llm("openai:gpt-4o-mini", api_key="sk-test")
    assert m.reasoning_effort is None


def test_build_llm_treats_empty_reasoning_effort_as_unset():
    """Env vars arrive as "" when undefined — that must not reach the API."""
    m = build_llm("openai:gpt-4o-mini", api_key="sk-test", reasoning_effort="")
    assert m.reasoning_effort is None


def test_build_llm_fake_prefix_ignores_reasoning_effort():
    from accordance.llm.adapter import FakeJudgeLLM

    m = build_llm("fake:fake", reasoning_effort="high")
    assert isinstance(m, FakeJudgeLLM)


# ── service tier (flex) ──────────────────────────────────────────────
# Flex trades latency for ~50% off. Blank must mean "send nothing": the dev
# Codex proxy ACCEPTS service_tier and silently ignores it (it echoes
# service_tier=None even when priority is requested), so a default value
# would create the illusion of a discount that was never applied.


def test_build_llm_forwards_service_tier():
    m = build_llm("openai:gpt-4o-mini", api_key="sk-test", service_tier="flex")
    assert m.service_tier == "flex"


def test_build_llm_omits_service_tier_by_default():
    m = build_llm("openai:gpt-4o-mini", api_key="sk-test")
    assert m.service_tier is None


def test_build_llm_treats_empty_service_tier_as_unset():
    m = build_llm("openai:gpt-4o-mini", api_key="sk-test", service_tier="")
    assert m.service_tier is None


def test_build_llm_fake_prefix_ignores_service_tier():
    from accordance.llm.adapter import FakeJudgeLLM

    m = build_llm("fake:fake", service_tier="flex")
    assert isinstance(m, FakeJudgeLLM)


# ── flex capacity fallback ───────────────────────────────────────────
# Flex answers 429 resource_unavailable when capacity is short. Without a
# fallback a capacity dip leaves error findings scattered through the report;
# with one, the run always completes and the worst case is today's price.


class _Boom(BaseChatModel):
    """Chat model that always raises the given exception."""

    exc: object = None

    @property
    def _llm_type(self) -> str:
        return "boom"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise self.exc


def _rate_limit_error(code="resource_unavailable"):
    import httpx
    from openai import RateLimitError

    return RateLimitError(
        code,
        response=httpx.Response(429, request=httpx.Request("POST", "http://x")),
        body={"error": {"code": code}},
    )


def _fallbacks():
    from accordance.llm.adapter import fallback_count_snapshot

    return fallback_count_snapshot()


def test_flex_falls_back_to_standard_on_capacity_429():
    from accordance.llm.adapter import FakeJudgeLLM, _TieredChatModel

    before = _fallbacks()
    m = _TieredChatModel(primary=_Boom(exc=_rate_limit_error()), fallback=FakeJudgeLLM())
    out = m.invoke("judge this")
    assert "status" in str(out)
    assert _fallbacks() == before + 1


def test_ordinary_rate_limits_do_not_fall_back_to_full_price():
    """A TPM 429 wants backoff, not an immediate re-run at the standard rate.

    `rate_limit_exceeded` and `insufficient_quota` are the same RateLimitError
    class as a capacity refusal, so matching on type alone doubled the bill on
    every throttle and made a dead key cost twice before failing.
    """
    import pytest
    from openai import RateLimitError

    from accordance.llm.adapter import FakeJudgeLLM, _TieredChatModel

    for code in ("rate_limit_exceeded", "insufficient_quota"):
        before = _fallbacks()
        m = _TieredChatModel(
            primary=_Boom(exc=_rate_limit_error(code)), fallback=FakeJudgeLLM()
        )
        with pytest.raises(RateLimitError):
            m.invoke("judge this")
        assert _fallbacks() == before, f"{code} must not fall back"


def test_non_capacity_errors_are_not_retried_on_the_standard_tier():
    """A bad request must surface, not silently re-run at full price."""
    from accordance.llm.adapter import FakeJudgeLLM, _TieredChatModel

    before = _fallbacks()
    m = _TieredChatModel(primary=_Boom(exc=ValueError("bad prompt")), fallback=FakeJudgeLLM())
    try:
        m.invoke("judge this")
        raise AssertionError("expected ValueError to propagate")
    except ValueError:
        pass
    assert _fallbacks() == before


def test_flex_wrapper_keeps_provider_enforced_structured_output():
    """The wrapper must not swallow with_structured_output.

    langchain_core's base implementation raises NotImplementedError unless
    bind_tools is overridden, so an un-delegated wrapper sent every judge call
    into judge_disclosure's unstructured except-branch — discarding the
    json_schema+strict constraint on 100% of disclosures under LLM_SERVICE_TIER=flex.
    """
    from accordance.judge.output_schema import JudgeOutput

    tiered = build_llm("openai:gpt-4o-mini", api_key="sk-test", service_tier="flex")
    # Must not raise, and must reach the real client so method/strict survive.
    assert tiered.with_structured_output(JudgeOutput, method="json_schema", strict=True)
    assert tiered.bind_tools([JudgeOutput]) is not None


def test_build_llm_wraps_only_when_flex_is_requested():
    from accordance.llm.adapter import _TieredChatModel

    plain = build_llm("openai:gpt-4o-mini", api_key="sk-test")
    assert not isinstance(plain, _TieredChatModel)
    tiered = build_llm("openai:gpt-4o-mini", api_key="sk-test", service_tier="flex")
    assert isinstance(tiered, _TieredChatModel)
    # model attribution must survive the wrapper (traces read model_name)
    assert tiered.model_name == plain.model_name


def test_priority_tier_is_not_wrapped():
    """Only flex can be capacity-refused; priority falls back on its own."""
    from accordance.llm.adapter import _TieredChatModel

    m = build_llm("openai:gpt-4o-mini", api_key="sk-test", service_tier="priority")
    assert not isinstance(m, _TieredChatModel)
    assert m.service_tier == "priority"
