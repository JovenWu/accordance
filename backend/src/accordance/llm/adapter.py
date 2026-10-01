import logging
import threading

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)

# Capacity refusals are the ONLY 429 that may fall back to the standard tier.
# OpenAI signals them with this error code; an ordinary quota/TPM 429
# ('rate_limit_exceeded') and a dead key ('insufficient_quota') must NOT
# trigger a retry at full price — the first wants backoff, the second wants to
# fail loudly. Matching every RateLimitError doubled the bill on any throttle.
_CAPACITY_REFUSAL_CODES = {"resource_unavailable", "service_tier_capacity_exceeded"}


def _is_capacity_refusal(exc: BaseException) -> bool:
    """True only for a flex capacity refusal, not for ordinary rate limiting."""
    try:
        from openai import RateLimitError
    except ImportError:  # non-OpenAI provider — nothing to special-case
        return False
    if not isinstance(exc, RateLimitError):
        return False
    code = getattr(exc, "code", None)
    if code is None:
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            code = (body.get("error") or {}).get("code") if isinstance(
                body.get("error"), dict
            ) else body.get("code")
    return code in _CAPACITY_REFUSAL_CODES


# Per-thread count of flex calls that fell back to the standard tier. The judge
# fan-out runs one disclosure per thread, so a thread-local lets
# graph.nodes attribute the missed discount to the RIGHT disclosure's usage row
# — a process-wide counter could not, and pricing a fallen-back call at the
# flex rate under-reports it 2x.
_fallbacks = threading.local()


def fallback_count_snapshot() -> int:
    """Flex→standard fallbacks recorded on THIS thread so far."""
    return getattr(_fallbacks, "count", 0)


def _note_capacity_fallback() -> int:
    _fallbacks.count = fallback_count_snapshot() + 1
    logger.warning(
        "flex capacity unavailable; retrying at the standard tier "
        "(fallbacks on this thread: %d). This call is billed at full price.",
        _fallbacks.count,
    )
    return _fallbacks.count


def _tiered_runnable(primary, fallback):
    """Run `primary`, retrying on `fallback` only for a flex capacity refusal.

    Runnable.with_fallbacks can't express this: it matches on exception TYPE,
    and an ordinary 429 is the same RateLimitError class as a capacity refusal.
    Retrying those at full price is exactly what must not happen, so the
    predicate stays explicit.
    """
    from langchain_core.runnables import RunnableLambda

    def _invoke(inp):
        try:
            return primary.invoke(inp)
        except Exception as e:
            if not _is_capacity_refusal(e):
                raise
            _note_capacity_fallback()
            return fallback.invoke(inp)

    return RunnableLambda(_invoke)


class _TieredChatModel(BaseChatModel):
    """Flex-first chat model that falls back to the standard tier on 429.

    Flex trades latency for ~50% off, but the provider may refuse it outright
    when capacity is short (429 resource_unavailable) — and it does NOT
    silently downgrade. Without a fallback a capacity dip scatters error
    findings through a report; with one, the run always completes and the worst
    case is what the standard tier costs today.

    ONLY capacity refusals fall back. A 400, a timeout or a bad prompt must
    surface rather than silently re-running at full price.

    Every model-facing entry point must be delegated, not just ``_generate``.
    ``bind_tools`` and ``with_structured_output`` are NOT inherited usefully:
    langchain_core's base ``with_structured_output`` raises NotImplementedError
    unless ``bind_tools`` is overridden, so an un-delegated wrapper made
    ``judge_disclosure`` fall into its unstructured except-branch on EVERY
    disclosure — silently discarding the provider-side schema constraint
    (`method="json_schema", strict=True`) that stops an invalid enum being
    generated. Observed in production: three consecutive runs at 100%
    `parse_path='fallback'` with zero structured parses.

    Missed discounts are recorded per thread (see ``fallback_count_snapshot``)
    so the disclosure that actually paid full price is the one billed for it.
    """

    primary: BaseChatModel
    fallback: BaseChatModel

    @property
    def _llm_type(self) -> str:
        return "tiered"

    @property
    def model_name(self) -> str:
        # Traces and usage rows attribute by model name; the wrapper must not
        # mask it (see judge.core._model_id_of).
        for attr in ("model_name", "model", "model_id"):
            val = getattr(self.primary, attr, None)
            if val:
                return str(val)
        return type(self.primary).__name__

    @property
    def service_tier(self):
        """The tier actually requested. Delegated so the wrapper stays
        introspectable — startup checks and tests read this off the built
        model and shouldn't have to know a wrapper is in the way."""
        return getattr(self.primary, "service_tier", None)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        try:
            return self.primary._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        except Exception as e:
            if not _is_capacity_refusal(e):
                raise
            _note_capacity_fallback()
            return self.fallback._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def bind_tools(self, tools, **kwargs):
        return _tiered_runnable(
            self.primary.bind_tools(tools, **kwargs),
            self.fallback.bind_tools(tools, **kwargs),
        )

    def with_structured_output(self, schema, **kwargs):
        """Delegate to the REAL client so `method`/`strict` reach the provider.

        The base implementation would pop both and route through bind_tools —
        i.e. plain function calling, which does not constrain decoding. That is
        the whole point of asking for json_schema, so it must not be inherited.
        """
        return _tiered_runnable(
            self.primary.with_structured_output(schema, **kwargs),
            self.fallback.with_structured_output(schema, **kwargs),
        )


class FakeJudgeLLM(BaseChatModel):
    """Returns a canned judge-shaped JSON. Used in tests."""

    @property
    def _llm_type(self) -> str:
        return "fake-judge"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.outputs import ChatGeneration, ChatResult

        canned = (
            '{"status":"partial","elements":[{"id":"x","status":"found","page":1}],'
            '"note":"fake","evidence_excerpt":"fake","evidence_page":1,'
            '"needs_vision_fallback":false}'
        )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=canned))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def build_llm(
    model: str,
    temperature: float = 0.0,
    base_url: str = "",
    api_key: str = "",
    max_retries: int = 2,
    timeout: float = 60.0,
    reasoning_effort: str = "",
    service_tier: str = "",
) -> BaseChatModel:
    """Build a LangChain chat model from a `provider:model` string.

    For `openai:`-prefixed models, `base_url` and `api_key` are forwarded to
    the underlying ChatOpenAI client — so you can route Anthropic models
    through an OpenAI-compatible proxy (LiteLLM, OpenRouter, corporate
    gateway, etc.). `max_retries` bounds SDK-level retries for 429/5xx
    errors; `timeout` sets the per-request deadline in seconds (forwarded as
    `request_timeout` on ChatOpenAI, preventing indefinite hangs against
    unreachable endpoints).

    `reasoning_effort` tunes how many reasoning tokens the model spends. Those
    bill as OUTPUT tokens, so it is a direct cost and latency lever. Blank
    means "don't send the parameter at all" — non-reasoning models and some
    proxies reject it outright, so it must stay opt-in. Accepted values vary
    BY MODEL (gpt-5.6-luna takes none/low/medium/high/xhigh/max and rejects
    'minimal'), so the value is passed through unvalidated: the provider
    returns a 400 listing what it supports.

    `service_tier` selects a processing tier ('flex' is roughly half price for
    higher latency, 'priority' the reverse, 'auto' the provider default).
    Blank sends nothing.

    WARNING: an endpoint that doesn't implement tiers may ACCEPT the parameter
    and ignore it. The dev Codex proxy does exactly that — HTTP 200 with
    `service_tier: null` in the response even when 'priority' is requested.
    There is no error to catch, so a tier can look applied while you pay full
    price. Confirm the response echoes the tier you asked for.

    Supports any provider that LangChain's init_chat_model accepts
    (anthropic, openai, google_genai, ollama, etc.). Plus 'fake:fake'
    for tests.
    """
    if model.startswith("fake:"):
        return FakeJudgeLLM()

    from langchain.chat_models import init_chat_model

    kwargs: dict = {"temperature": temperature, "max_retries": max_retries, "timeout": timeout}
    if base_url:
        kwargs["base_url"] = base_url
    if api_key:
        kwargs["api_key"] = api_key
    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort
    if service_tier:
        kwargs["service_tier"] = service_tier
    llm = init_chat_model(model, **kwargs)

    # Only flex can be capacity-refused. 'priority' and 'auto' are always
    # served, so wrapping them would add a pointless indirection.
    if service_tier == "flex":
        standard = dict(kwargs)
        standard.pop("service_tier", None)
        return _TieredChatModel(primary=llm, fallback=init_chat_model(model, **standard))
    return llm
