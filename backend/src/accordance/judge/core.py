import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from accordance.judge.output_schema import DisclosureStatus, JudgeOutput
from accordance.judge.prompts import (
    PROMPT_HASH,
    SYSTEM_PROMPT,
    USER_TEMPLATE,
    render_chunks,
    render_elements_list,
    render_hints,
)
from accordance.judge.snap import snap_excerpt
from accordance.judge.verify import verify_excerpt
from accordance.kb.schema import Disclosure

logger = logging.getLogger(__name__)

_TOKEN_ENCODER = None


def _estimate_tokens(text: str) -> int:
    """Approximate token count for the cost-estimate fallback (usage-stripped
    proxies). Uses tiktoken's cl100k_base; falls back to chars/4."""
    if not text:
        return 0
    global _TOKEN_ENCODER
    try:
        if _TOKEN_ENCODER is None:
            import tiktoken

            _TOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")
        return len(_TOKEN_ENCODER.encode(text))
    except Exception:
        return max(1, len(text) // 4)


Retriever = Callable[[str, int], list[dict]]


def _build_system_message(cache: bool) -> SystemMessage:
    """System message for the judge.

    When `cache`, mark the (large, identical-across-the-fan-out) system prompt
    as an Anthropic cache breakpoint via the content-block form, so providers/
    proxies that honor `cache_control` can reuse it across the 38 judge calls.
    Plain string form otherwise.
    """
    if cache:
        return SystemMessage(
            content=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        )
    return SystemMessage(content=SYSTEM_PROMPT)


_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?```\s*$", re.DOTALL
)


def _extract_json(text: str) -> str:
    """Best-effort extract a JSON object string from an LLM response.

    Handles three cases:
      1. The response is already raw JSON.
      2. The response is wrapped in a markdown code fence (```json ... ```).
      3. The response has prose before/after a JSON object; we slice from
         the first '{' to the matching final '}'.
    """
    text = text.strip()

    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()

    if text.startswith("{") or text.startswith("["):
        return text

    # Prose around JSON — slice from the first { to the last }
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        return text[first : last + 1]

    return text


@dataclass
class JudgeTrace:
    """Observability record for a single LLM judge call.

    Persisted to the judge_traces table. Re-judged disclosures produce
    multiple traces tied to the same (run_id, disclosure_id).
    """

    chunk_ids: list[int]
    distances: list[float]
    pages: list[int]
    queries_used: list[str]
    parse_path: str  # 'structured' | 'fallback' | 'error'
    error: str | None
    latency_ms: int
    prompt_hash: str
    model_id: str
    rejudged: bool = False
    elements_seen: list[str] = field(default_factory=list)
    # True when evidence_excerpt was found in (or paraphrased from) one of
    # the retrieved chunks; False when it appears to be hallucinated; None
    # when the LLM returned no excerpt at all. See judge/verify.py.
    evidence_verified: bool | None = None
    # When evidence_verified is False, we null out the user-facing excerpt
    # in JudgeOutput. The original is kept here for debugging.
    original_evidence_excerpt: str | None = None
    # Token-count estimate of this call's prompt/response, used only as the
    # cost fallback when the provider/proxy returns no usage_metadata.
    est_input_tokens: int | None = None
    est_output_tokens: int | None = None


def _model_id_of(llm: BaseChatModel) -> str:
    # LangChain doesn't expose a single canonical "model id" field; try a
    # few common attributes and fall back to the class name.
    for attr in ("model_name", "model", "model_id"):
        val = getattr(llm, attr, None)
        if val:
            return str(val)
    return type(llm).__name__


def judge_disclosure(
    disclosure: Disclosure,
    retrieve: Retriever,
    llm: BaseChatModel,
    k: int = 5,
    *,
    override_queries: list[str] | None = None,
    per_element: bool = True,
    reranker=None,            # Reranker | None
    rerank_top_n: int = 15,
    cache_system: bool = False,
    tag_retrieve=None,        # Callable[[int], list[dict]] | None — force-include tagged chunks
    tag_limit: int = 5,
    page_text_provider: Callable[[int], str] | None = None,
    page_sibling_store=None,  # VectorStore | None — for page-coherent sibling swap
    run_id: str | None = None,
    page_coherent: bool = True,
    structured_method: str = "json_schema",
) -> tuple[JudgeOutput | None, JudgeTrace]:
    """Run the per-disclosure RAG + judge and return (output, trace).

    Returns a (None, trace) tuple when the LLM call fails — callers decide
    whether to surface that as an error finding or retry.

    Retrieval query strategy:
    - `override_queries` (used by re-judge): exactly those queries.
    - `per_element=True` (default): disclosure.retrieval_queries UNION the
      description of every required element. Tackles cross-page disclosures
      where individual elements live on different pages.
    - `per_element=False`: legacy behavior — disclosure.retrieval_queries only.
    """
    if override_queries is not None:
        queries = list(override_queries)
    elif per_element:
        queries = list(disclosure.retrieval_queries) + [
            e.desc for e in disclosure.required_elements
        ]
    else:
        queries = list(disclosure.retrieval_queries)

    seen: set[int] = set()
    merged: list[dict] = []
    for q in queries:
        for chunk in retrieve(q, k):
            if chunk["chunk_id"] not in seen:
                seen.add(chunk["chunk_id"])
                merged.append(chunk)
    if reranker is not None and merged:
        rerank_query = f"{disclosure.title}. {disclosure.requirement_text}"
        order = reranker.rerank(rerank_query, [c["text"] for c in merged], rerank_top_n)
        seen_idx: set[int] = set()
        valid_order = []
        for i in order:
            if 0 <= i < len(merged) and i not in seen_idx:
                seen_idx.add(i)
                valid_order.append(i)
        merged = [merged[i] for i in valid_order]
    else:
        merged.sort(key=lambda c: (c["page"], c["chunk_id"]))

    # Page-coherent sibling swap (cost-neutral for the swap itself).
    #
    # Problem: a table/picture chunk that shares a page with a retrieved
    # narrative chunk often embeds poorly (garbled text, missing keywords) and
    # ranks below the top-k cut.  The judge never sees the numbers and marks
    # the disclosure partial/missing.
    #
    # Fix: after the normal merge+sort, find chunks on the SAME PAGE as the
    # top-ranked hits that are NOT already in the pool, then SWAP each sibling
    # in for the WEAKEST member by relevance score (distance), keeping
    # len(merged) CONSTANT.
    #
    # N-cap: at most N = max(1, k // 3) siblings may be swapped in per call.
    # This prevents the swap from evicting most of the genuinely-retrieved pool
    # (e.g. k=6 → cap=2; k=3 → cap=1).
    #
    # Token-neutrality: the swap itself is token-neutral (each sibling is
    # truncated to the displaced member's character length).  Note: the
    # tag-aware force-include step that follows may add tokens on top.
    #
    # Reranker guard: when a reranker is active, its ranked ordering is the
    # ground truth for "weakest."  However, the reranker may have deliberately
    # evicted a sibling from the pool; re-inserting it would silently undo
    # that decision.  To avoid this, the page-coherent swap is skipped
    # entirely when a reranker is active.  The reranker is off by default, so
    # this gate fires only in explicit reranker configurations.
    #
    # Gated by page_coherent flag (default True per Settings.retrieval_page_coherent).
    if page_coherent and page_sibling_store is not None and run_id is not None and merged:
        # Skip when a reranker is active: the reranker may have deliberately
        # evicted a sibling; re-inserting it would silently undo that decision.
        _swap_eligible = reranker is None
        if _swap_eligible:
            try:
                n_cap = max(1, k // 3)
                # Use ALL pages in the pool as sibling candidates (every page in
                # merged may have missed table chunks).
                hot_pages = list({c["page"] for c in merged})
                existing_ids = [c["chunk_id"] for c in merged]
                siblings = page_sibling_store.retrieve_page_siblings(
                    run_id=run_id,
                    pages=hot_pages,
                    exclude_ids=existing_ids,
                    limit=n_cap * max(1, len(hot_pages)),
                )
                # Build a slot cursor that advances through the weakest members
                # (sorted by worst distance = highest distance value).
                # Each sibling gets its OWN slot — do NOT reuse merged[-1].
                # Sort merged by descending distance to find the N weakest.
                sorted_by_weakness = sorted(
                    range(len(merged)), key=lambda i: -merged[i]["distance"]
                )
                slot_cursor = 0  # which weakness-rank slot to displace next
                for sibling in siblings[:n_cap]:
                    if slot_cursor >= len(sorted_by_weakness):
                        break
                    # The weakest available slot (by actual relevance score).
                    weakest_idx = sorted_by_weakness[slot_cursor]
                    slot_cursor += 1
                    weakest = merged[weakest_idx]
                    # Token-neutrality guard: truncate sibling text to the
                    # displaced member's char length (1 token ≈ 4 chars).
                    max_len = len(weakest["text"])
                    if len(sibling["text"]) > max_len:
                        sibling = dict(sibling)  # don't mutate the list element
                        sibling["text"] = sibling["text"][:max_len]
                    # Swap: replace weakest with sibling in its own slot.
                    merged[weakest_idx] = sibling
            except Exception as e:
                logger.warning(
                    "page-coherent swap failed for %s: %s", disclosure.id, e
                )

    # Tag-aware retrieval: the report tags its own data tables with the GRI
    # disclosure id (e.g. "[[GRI 303-4]]"). Force-include those chunks (FIRST,
    # highest precision) so the judge always sees the report's own data table,
    # even if the reranker would have cut it.
    if tag_retrieve is not None:
        try:
            present = {c["chunk_id"] for c in merged}
            tag_chunks = [c for c in tag_retrieve(tag_limit) if c["chunk_id"] not in present]
            if tag_chunks:
                merged = tag_chunks + merged
        except Exception:
            pass  # tag retrieval is best-effort; fall back to the reranked pool

    user = USER_TEMPLATE.format(
        disclosure_id=disclosure.id,
        disclosure_title=disclosure.title,
        standard=disclosure.standard,
        requirement_text=disclosure.requirement_text,
        elements_list=render_elements_list(disclosure.required_elements),
        evidence_hints=render_hints(disclosure.good_evidence_hints),
        retrieved_chunks=render_chunks(merged),
    )
    messages = [_build_system_message(cache_system), HumanMessage(content=user)]

    t0 = time.monotonic()
    out: JudgeOutput | None = None
    err: str | None = None
    # Try LangChain's structured-output path first. With native Anthropic /
    # OpenAI clients this uses tool/function calling and returns a parsed
    # JudgeOutput directly. With some OpenAI-compatible proxies it fails
    # or returns markdown-wrapped JSON; we fall back to plain text + manual
    # extraction in that case.
    parse_path = "structured"
    try:
        # `json_schema` + strict makes the PROVIDER constrain decoding to the
        # schema, so an invalid enum (the observed failure: status="found",
        # which is the ELEMENT vocabulary) cannot be generated at all. The
        # default `function_calling` method only validates client-side, after
        # the call is already paid for. Configurable because a proxy that
        # rejects json_schema would otherwise burn a failed call plus a
        # fallback call on every disclosure.
        kwargs = (
            {"method": "json_schema", "strict": True}
            if structured_method == "json_schema"
            else {}
        )
        structured = llm.with_structured_output(JudgeOutput, **kwargs)
        out = structured.invoke(messages)
    except Exception:
        parse_path = "fallback"
        try:
            resp = llm.invoke(messages)
            content = resp.content if hasattr(resp, "content") else str(resp)
            if isinstance(content, list):
                # Some LangChain responses contain a list of content blocks
                content = "".join(
                    (c.get("text", "") if isinstance(c, dict) else str(c))
                    for c in content
                )
            out = JudgeOutput.model_validate_json(_extract_json(content))
        except Exception as e2:
            parse_path = "error"
            err = str(e2)

    latency_ms = int((time.monotonic() - t0) * 1000)

    # Evidence handling. When a page_text_provider is supplied (the live run
    # path), SNAP the excerpt to verbatim PDF page text — replacing the LLM's
    # paraphrase with the exact words on the page so the viewer highlights it
    # precisely, and correcting the cited page when the quote is really on
    # another retrieved page. An excerpt that can't be located verbatim is
    # dropped (better no quote than a wrong one). Without a provider (eval,
    # tests) we fall back to the cheap substring hallucination guard.
    evidence_verified: bool | None = None
    original_excerpt: str | None = None
    if out is not None:
        if out.evidence_excerpt:
            original_excerpt = out.evidence_excerpt
            if page_text_provider is not None:
                snapped, snapped_page = snap_excerpt(
                    out.evidence_excerpt,
                    out.evidence_page,
                    [c["page"] for c in merged],
                    page_text_provider,
                )
                out.evidence_excerpt = snapped
                out.evidence_page = snapped_page
                evidence_verified = snapped is not None
            else:
                evidence_verified = verify_excerpt(out.evidence_excerpt, merged)
                if not evidence_verified:
                    out.evidence_excerpt = None
                    out.evidence_page = None
        else:
            evidence_verified = None

    trace = JudgeTrace(
        chunk_ids=[c["chunk_id"] for c in merged],
        distances=[float(c.get("distance", 0.0)) for c in merged],
        pages=[c["page"] for c in merged],
        queries_used=queries,
        parse_path=parse_path,
        error=err,
        latency_ms=latency_ms,
        prompt_hash=PROMPT_HASH,
        model_id=_model_id_of(llm),
        elements_seen=[e.id for e in out.elements] if out else [],
        evidence_verified=evidence_verified,
        original_evidence_excerpt=original_excerpt,
        est_input_tokens=_estimate_tokens(SYSTEM_PROMPT) + _estimate_tokens(user),
        est_output_tokens=_estimate_tokens(out.model_dump_json()) if out is not None else 0,
    )
    return out, trace


def judge_disclosure_with_rejudge(
    disclosure: Disclosure,
    retrieve: Retriever,
    llm: BaseChatModel,
    k: int = 5,
    *,
    rejudge_on_missing: bool = True,
    per_element: bool = True,
    reranker=None,            # Reranker | None
    rerank_top_n: int = 15,
    cache_system: bool = False,
    tag_retrieve=None,        # Callable[[int], list[dict]] | None — force-include tagged chunks
    tag_limit: int = 5,
    page_text_provider: Callable[[int], str] | None = None,
    page_sibling_store=None,  # VectorStore | None — for page-coherent sibling swap
    run_id: str | None = None,
    page_coherent: bool = True,
    structured_method: str = "json_schema",
) -> tuple[JudgeOutput | None, list[JudgeTrace]]:
    """Judge a disclosure, then re-judge if the first verdict is 'missing'.

    The first pass uses `disclosure.retrieval_queries` plus (when
    `per_element=True`) the element descriptions. If it returns `missing`,
    a second pass retrieves with element descriptions *only* and doubles k
    — this concentrates the chunk pool on per-element specifics in case
    the broader first-pass retrieval drowned them out. We only override
    the verdict if the second pass produces a non-missing answer.

    Returns (final_output, [trace_1, trace_2?]). Both traces are persisted
    even when the first verdict wins, so we can later measure how often
    the re-judge actually changes the outcome.
    """
    out1, trace1 = judge_disclosure(
        disclosure, retrieve, llm, k=k, per_element=per_element,
        reranker=reranker, rerank_top_n=rerank_top_n, cache_system=cache_system,
        tag_retrieve=tag_retrieve, tag_limit=tag_limit,
        page_text_provider=page_text_provider,
        page_sibling_store=page_sibling_store, run_id=run_id, page_coherent=page_coherent,
        structured_method=structured_method,
    )
    traces = [trace1]

    if (
        not rejudge_on_missing
        or out1 is None
        or out1.status != DisclosureStatus.missing
    ):
        return out1, traces

    element_queries = [e.desc for e in disclosure.required_elements]
    out2, trace2 = judge_disclosure(
        disclosure,
        retrieve,
        llm,
        k=k * 2,
        override_queries=element_queries,
        reranker=reranker,
        rerank_top_n=rerank_top_n,
        cache_system=cache_system,
        tag_retrieve=tag_retrieve,
        tag_limit=tag_limit,
        page_text_provider=page_text_provider,
        page_sibling_store=page_sibling_store, run_id=run_id, page_coherent=page_coherent,
        structured_method=structured_method,
    )
    trace2.rejudged = True
    traces.append(trace2)

    if out2 is not None and out2.status != DisclosureStatus.missing:
        return out2, traces
    return out1, traces
