import json
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

import psycopg
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.tracers.context import register_configure_hook

from accordance.db import connection as db_connection
from accordance.extractor import extract_pdf
from accordance.indexer.chunker import chunk_report
from accordance.indexer.vector_store import VectorStore
from accordance.judge.core import JudgeTrace, judge_disclosure_with_rejudge
from accordance.judge.output_schema import JudgeOutput
from accordance.judge.prompts import PROMPT_HASH
from accordance.judge.rollup import compute_score
from accordance.judge.snap import make_page_text_provider, snap_excerpt
from accordance.kb.schema import Disclosure
from accordance.llm.adapter import fallback_count_snapshot

logger = logging.getLogger(__name__)

_usage_cb_var: ContextVar[UsageMetadataCallbackHandler | None] = ContextVar(
    "gri_usage_metadata_cb", default=None
)
register_configure_hook(_usage_cb_var, inheritable=True)


@contextmanager
def _usage_callback():
    """Drop-in, leak-free replacement for get_usage_metadata_callback().

    Yields a UsageMetadataCallbackHandler whose `.usage_metadata` dict
    aggregates token usage from LLM calls made within the context (same shape
    as the stock helper).
    """
    cb = UsageMetadataCallbackHandler()
    token = _usage_cb_var.set(cb)
    try:
        yield cb
    finally:
        _usage_cb_var.reset(token)


_judge_sem: threading.Semaphore | None = None
_judge_sem_lock = threading.Lock()


def _get_judge_sem() -> threading.Semaphore:
    global _judge_sem
    if _judge_sem is None:
        with _judge_sem_lock:
            if _judge_sem is None:
                from accordance.config import get_settings

                _judge_sem = threading.Semaphore(get_settings().judge_concurrency)
    return _judge_sem


class _VisionBudget:
    """Per-run cap on vision re-judge calls, shared across the fan-out.

    The LangGraph `Send` fan-out runs each disclosure in its own thread, so
    the counter needs a lock. Keyed by run_id; run_ids are unique UUIDs so
    keys never collide across runs (no reset needed).
    """

    def __init__(self) -> None:
        self._used: dict[str, int] = {}
        self._lock = threading.Lock()

    def take(self, run_id: str, limit: int) -> bool:
        """Claim one vision call for `run_id`. Returns False when exhausted."""
        with self._lock:
            used = self._used.get(run_id, 0)
            if used >= limit:
                return False
            self._used[run_id] = used + 1
            return True


_vision_budget = _VisionBudget()


def _persist_traces(
    conn: psycopg.Connection,
    run_id: str,
    disclosure_id: str,
    traces: list[JudgeTrace],
) -> None:
    """Insert one row per attempt into judge_traces.

    Failures here are swallowed — we don't want a trace-write to fail the
    whole run. Tracing is best-effort observability, not source of truth.
    """
    if not traces:
        return
    try:
        for attempt, t in enumerate(traces, start=1):
            conn.execute(
                """
                INSERT INTO judge_traces
                    (run_id, disclosure_id, attempt, rejudged, prompt_hash,
                     model, queries_json, chunk_ids_json, distances_json,
                     pages_json, parse_path, error, latency_ms,
                     evidence_verified)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    disclosure_id,
                    attempt,
                    t.rejudged,
                    t.prompt_hash,
                    t.model_id,
                    json.dumps(t.queries_used),
                    json.dumps(t.chunk_ids),
                    json.dumps(t.distances),
                    json.dumps(t.pages),
                    t.parse_path,
                    t.error,
                    t.latency_ms,
                    t.evidence_verified,
                ),
            )
    except Exception:
        pass


class RetrievalError(RuntimeError):
    """Retrieval failed (query embedding or vector search) — NOT the judge LLM.

    Exists purely so judge_one_node can attribute a failure to the right
    subsystem: the two use different endpoints and credentials, and conflating
    them points debugging at the wrong service.
    """


@dataclass
class UsageRecord:
    """One paid API call's token usage, pending cost computation + persistence.

    ``input_tokens`` is the TOTAL prompt size; the two cache fields are SUBSETS
    of it (the convention OpenAI and LangChain both use), priced separately by
    pricing.cost_usd.
    """

    kind: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    service_tier: str = ""


def _persist_usage(conn: psycopg.Connection, run_id: str, records: list[UsageRecord]) -> None:
    """Insert one llm_usage row per record, priced + attributed to the run owner.

    Best-effort: a failure here must never fail the run (mirrors _persist_traces).
    user_id is denormalized from runs.created_by so the row stays attributable
    after the report is deleted.
    """
    if not records:
        return
    try:
        from accordance.config import get_settings
        from accordance.pricing import cost_usd, load_prices

        owner = conn.execute("SELECT created_by FROM runs WHERE id=%s", (run_id,)).fetchone()
        user_id = owner["created_by"] if owner else None
        prices = load_prices(get_settings())
        for r in records:
            cost = cost_usd(
                r.model,
                r.input_tokens,
                r.output_tokens,
                prices,
                cached_tokens=r.cached_input_tokens,
                cache_write_tokens=r.cache_write_tokens,
                service_tier=r.service_tier,
            )
            conn.execute(
                "INSERT INTO llm_usage "
                "(run_id, user_id, kind, model, input_tokens, output_tokens, "
                " cached_input_tokens, cache_write_tokens, cost_usd) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    run_id,
                    user_id,
                    r.kind,
                    r.model,
                    r.input_tokens,
                    r.output_tokens,
                    r.cached_input_tokens,
                    r.cache_write_tokens,
                    cost,
                ),
            )
    except Exception:
        logger.warning("_persist_usage failed; skipping cost capture", exc_info=True)


def _judge_usage_with_fallback(
    usage_md: dict | None, traces: list, *, tier_downgraded: bool = False
) -> list[UsageRecord]:
    """Judge-call UsageRecords, back-filling either side the provider omitted.

    Provider counts always win; the tiktoken estimate on JudgeTrace only fills
    a side the provider reported as zero. The fallback is PER SIDE because a
    proxy can return usage_metadata carrying input tokens and a zero output
    count — an all-or-nothing guard sees a non-empty record list, skips the
    estimate, and silently persists output_tokens=0 (observed on a prod run
    that booked 366k input against no output at all).
    """
    records = _usage_records_from_callback(
        usage_md, "judge", tier_downgraded=tier_downgraded
    )
    est_in = sum((t.est_input_tokens or 0) for t in traces)
    est_out = sum((t.est_output_tokens or 0) for t in traces)

    if not records:
        if traces and (est_in or est_out):
            return [UsageRecord("judge", traces[0].model_id, est_in, est_out)]
        return []

    if est_in and not sum(r.input_tokens for r in records):
        records[0].input_tokens = est_in
    if est_out and not sum(r.output_tokens for r in records):
        records[0].output_tokens = est_out
    return records


def _usage_records_from_callback(
    usage_md: dict | None, kind: str, *, tier_downgraded: bool = False
) -> list[UsageRecord]:
    """Convert a UsageMetadataCallbackHandler.usage_metadata dict (keyed by model
    name) into UsageRecords of the given kind.

    The prompt-cache split lives one level down, in ``input_token_details``
    (``cache_read`` / ``cache_creation``); ``input_tokens`` already includes it.
    Reading only the top-level fields billed every cache hit at the full input
    rate — a ~10x over-count on the ~25% of each judge prompt that is the
    shared system prefix.

    ``tier_downgraded`` says a flex call was capacity-refused and re-run on the
    standard tier, so it was billed at FULL price. Pricing it at the flex rate
    would under-report it 2x. The flag is per disclosure rather than per call:
    when only one of a judge+rejudge pair fell back we still bill the pair at
    standard, because over-counting is the safe direction.
    """
    from accordance.config import get_settings

    tier = "" if kind == "embedding" else (get_settings().llm_service_tier or "")
    if tier_downgraded:
        tier = ""
    records: list[UsageRecord] = []
    for model_name, md in (usage_md or {}).items():
        details = md.get("input_token_details") or {}
        records.append(
            UsageRecord(
                kind=kind,
                model=model_name,
                input_tokens=int(md.get("input_tokens", 0)),
                output_tokens=int(md.get("output_tokens", 0)),
                cached_input_tokens=_cache_tokens(details, "cache_read"),
                cache_write_tokens=_cache_tokens(details, "cache_creation"),
                service_tier=tier,
            )
        )
    return records


def _cache_tokens(details: dict, suffix: str) -> int:
    """Cache-token count from input_token_details, whatever the tier calls it.

    The flex tier renames these: OpenAI/OpenRouter flex returns
    `flex_cache_read` / `flex_cache_creation` rather than the plain names, so
    matching the exact key recorded 0 cached tokens on every flex call — a 10x
    over-count, on the very tier chosen to save money. Match by suffix and take
    the LARGEST value rather than summing: a provider that reports both an
    unprefixed and a tier-prefixed key is describing the same tokens twice.
    """
    values = [
        int(v or 0)
        for k, v in details.items()
        if isinstance(v, (int, float)) and str(k).endswith(suffix)
    ]
    return max(values) if values else 0


def snap_evidence_in_place(
    out: JudgeOutput,
    candidate_pages: list[int],
    get_page_text: Callable[[int], str],
) -> JudgeOutput:
    """Snap ``out.evidence_excerpt`` to verbatim page text, dropping it when it
    can't be located.

    Applied to the post-vision-merge output: the vision pass installs the
    model's raw image transcription (vision_fallback.merge_verdicts) which
    bypassed the text-path snap done inside judge_disclosure and may not exist
    in the page text layer — so the viewer would highlight gibberish or nothing.
    Idempotent for an already-snapped text-path excerpt (it re-snaps to itself).
    """
    if out is not None and out.evidence_excerpt:
        snapped, page = snap_excerpt(
            out.evidence_excerpt, out.evidence_page, candidate_pages, get_page_text
        )
        out.evidence_excerpt = snapped
        out.evidence_page = page
    return out


def extract_node(state: dict) -> dict:
    pdf_path = Path(state["pdf_path"])
    report = extract_pdf(pdf_path)
    return {"extraction": report}


def index_node(state: dict, store: VectorStore, conn: psycopg.Connection) -> dict:
    from accordance.config import get_settings
    from accordance.judge.core import _estimate_tokens

    chunks = chunk_report(state["extraction"])
    store.write(state["run_id"], chunks)

    try:
        total_tokens = sum(_estimate_tokens(c.text) for c in chunks)
        if total_tokens:
            _persist_usage(
                conn,
                state["run_id"],
                [
                    UsageRecord(
                        kind="embedding",
                        model=get_settings().embedding_model,
                        input_tokens=total_tokens,
                        output_tokens=0,
                    )
                ],
            )
    except Exception:
        logger.warning("embedding usage capture failed; cost undercounted", exc_info=True)

    return {"indexed": True}


def judge_one_node(
    state: dict,
    disclosure: Disclosure,
    store: VectorStore,
    llm: BaseChatModel,
    conn: psycopg.Connection,
    *,
    reranker=None,
    rerank_top_n: int = 15,
    cache_system: bool = False,
    tag_aware: bool = False,
    tag_limit: int = 5,
) -> dict:
    from accordance.api.cancellation import registry as cancel_registry
    from accordance.api.events import bus
    from accordance.config import get_settings, resolve_pdf_path

    if cancel_registry.is_cancelled(state["run_id"]):
        return {"findings": []}

    def retrieve(q: str, k: int):
        try:
            return store.retrieve(state["run_id"], q, k)
        except Exception as e:
            raise RetrievalError(str(e)) from e

    suggested_fix = disclosure.suggested_fix_template
    settings = get_settings()
    vision_used = False
    judge_error: str | None = None
    failure_stage = "judge"
    traces: list[JudgeTrace] = []
    out = None

    pdf_provider = None
    try:
        pdf_row = conn.execute(
            "SELECT pdf_path FROM runs WHERE id=%s", (state["run_id"],)
        ).fetchone()
        if pdf_row:
            pdf_provider = make_page_text_provider(
                resolve_pdf_path(pdf_row["pdf_path"], settings)
            )
    except Exception:
        pdf_provider = None

    class _EmptyUsageCb:
        def __init__(self):
            self.usage_metadata = {}

    judge_usage_cb: _EmptyUsageCb | object = _EmptyUsageCb()

    fallbacks_before = fallback_count_snapshot()

    try:
        tag_retrieve = (
            (lambda lim: store.retrieve_by_tag(state["run_id"], disclosure.id, lim))
            if tag_aware
            else None
        )
        with _usage_callback() as judge_usage_cb:
            out, traces = judge_disclosure_with_rejudge(
                disclosure=disclosure,
                retrieve=retrieve,
                llm=llm,
                rejudge_on_missing=settings.judge_rejudge_on_missing,
                per_element=settings.retrieval_per_element,
                reranker=reranker,
                rerank_top_n=rerank_top_n,
                cache_system=cache_system,
                tag_retrieve=tag_retrieve,
                tag_limit=tag_limit,
                page_text_provider=pdf_provider,
                page_sibling_store=store,
                run_id=state["run_id"],
                page_coherent=settings.retrieval_page_coherent,
                structured_method=settings.judge_structured_method,
            )
    except RetrievalError as e:
        judge_error = str(e)
        failure_stage = "retrieval"
        out = None
        traces = []
    except Exception as e:
        judge_error = str(e)
        out = None
        traces = []
    finally:
        if pdf_provider is not None:
            pdf_provider.close()

    want_vision = (
        out is not None
        and settings.vision_fallback_enabled
        and out.applicable
        and (
            out.needs_vision_fallback
            or (
                settings.vision_fallback_on_low_confidence
                and out.status.value in ("partial", "missing")
            )
        )
    )
    vision_usage_md: dict = {}
    if want_vision and _vision_budget.take(state["run_id"], settings.vision_fallback_budget):
        try:
            from collections import Counter

            from accordance.judge.vision_fallback import (
                judge_with_vision,
                merge_verdicts,
            )

            pdf_row = conn.execute(
                "SELECT pdf_path FROM runs WHERE id=%s", (state["run_id"],)
            ).fetchone()
            if pdf_row:
                page_freq: Counter[int] = Counter()
                for t in traces:
                    for p in t.pages:
                        page_freq[p] += 1
                candidate_pages = [p for p, _ in page_freq.most_common()] or [1]
                vpath = resolve_pdf_path(pdf_row["pdf_path"], settings)
                with _usage_callback() as vision_usage_cb:
                    vision_out = judge_with_vision(disclosure, vpath, candidate_pages, llm)
                vision_usage_md = vision_usage_cb.usage_metadata
                out = merge_verdicts(out, vision_out)
                vision_used = True
                vprovider = make_page_text_provider(vpath)
                try:
                    snap_evidence_in_place(out, candidate_pages, vprovider)
                finally:
                    vprovider.close()
        except Exception as e:
            logger.warning(
                "vision fallback failed for disclosure %s (run %s); "
                "keeping the text verdict: %s",
                disclosure.id,
                state["run_id"],
                str(e)[:200],
            )

    _persist_traces(conn, state["run_id"], disclosure.id, traces)

    tier_downgraded = fallback_count_snapshot() > fallbacks_before
    judge_records = _judge_usage_with_fallback(
        judge_usage_cb.usage_metadata, traces, tier_downgraded=tier_downgraded
    )
    vision_records = _usage_records_from_callback(
        vision_usage_md, "vision", tier_downgraded=tier_downgraded
    )
    _persist_usage(conn, state["run_id"], judge_records + vision_records)

    if out is None:
        status_value = "error"
        score = None
        na_reason = None
        err_detail = judge_error[:200] if judge_error else "unknown error"
        note = f"{failure_stage.capitalize()} failed: {err_detail}"
        logger.warning(
            "%s failed for disclosure %s (run %s): %s",
            failure_stage,
            disclosure.id,
            state["run_id"],
            err_detail,
        )
        evidence_excerpt = None
        evidence_page = None
        elements_payload = "[]"
    else:
        status_value = out.status.value
        score = compute_score(
            out.elements,
            out.applicable,
            disclosure.id,
            status=status_value,
            cutoff_low=settings.score_cutoff_low,
            cutoff_high=settings.score_cutoff_high,
        )
        na_reason = out.na_reason if score == 0 else None
        note = out.note
        evidence_excerpt = out.evidence_excerpt
        evidence_page = out.evidence_page
        elements_payload = json.dumps([e.model_dump(mode="json") for e in out.elements])

    conn.execute(
        """
        INSERT INTO findings
            (run_id, disclosure_id, standard, status, score, na_reason, note,
             evidence_excerpt, evidence_page, elements_json, suggested_fix,
             vision_fallback_used, prompt_hash)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(run_id, disclosure_id) DO UPDATE SET
            status = excluded.status,
            score = excluded.score,
            na_reason = excluded.na_reason,
            note = excluded.note,
            evidence_excerpt = excluded.evidence_excerpt,
            evidence_page = excluded.evidence_page,
            elements_json = excluded.elements_json,
            suggested_fix = excluded.suggested_fix,
            vision_fallback_used = excluded.vision_fallback_used,
            prompt_hash = excluded.prompt_hash
        """,
        (
            state["run_id"],
            disclosure.id,
            disclosure.standard,
            status_value,
            score,
            na_reason,
            note,
            evidence_excerpt,
            evidence_page,
            elements_payload,
            suggested_fix,
            vision_used,
            PROMPT_HASH,
        ),
    )

    bus.publish(
        state["run_id"],
        {
            "type": "finding",
            "disclosure_id": disclosure.id,
            "status": status_value,
            "score": score,
            "note": note,
        },
    )

    return {
        "findings": [
            {
                "disclosure_id": disclosure.id,
                "judgment": out,
                "suggested_fix": suggested_fix,
            }
        ]
    }


def judge_all_node(
    state: dict,
    disclosures: list[Disclosure],
    store: VectorStore,
    llm: BaseChatModel,
    conn: psycopg.Connection,
    *,
    reranker=None,
    rerank_top_n: int = 15,
    cache_system: bool = False,
    tag_aware: bool = False,
    tag_limit: int = 5,
    max_workers: int = 12,
) -> dict:
    """Judge every disclosure, running the per-disclosure judge calls CONCURRENTLY.

    This replaces a LangGraph ``Send`` fan-out. The synchronous ``graph.invoke()``
    executed the fanned-out judge branches SERIALLY, so a full run cost O(N) LLM
    round-trips end to end (a ~85-disclosure sector preset took ~1 hour). A thread
    pool delivers the concurrency the system was already built for; the global
    judge semaphore (acquired HERE in ``_one``, before the worker borrows a
    connection — see config.effective_pool_max_size, whose additive pool formula
    depends on that ordering) still caps LLM concurrency ACROSS simultaneous
    runs. ``max_workers`` is the per-run thread cap
    (``settings.judge_concurrency``).

    Each worker borrows its own connection from the shared Postgres pool via
    ``db_connection()``, so no connection is ever shared across threads. The
    ``conn`` parameter is kept for graph-wiring compatibility (build.py passes it)
    but is NOT used inside the fan-out. The pool's max_size (24) comfortably
    exceeds judge_concurrency, so workers never starve.

    Each ``judge_one_node`` writes its own finding row, so a single crashing
    disclosure can never sink the whole run — it is logged and yields no finding.
    """
    findings: list = []
    if not disclosures:
        return {"findings": findings}

    workers = max(1, min(max_workers, len(disclosures)))

    def _one(d: Disclosure) -> dict:
        try:
            with _get_judge_sem(), db_connection() as c:
                st = VectorStore(c, store.embedder, mode=store.mode)
                return judge_one_node(
                    state,
                    d,
                    st,
                    llm,
                    c,
                    reranker=reranker,
                    rerank_top_n=rerank_top_n,
                    cache_system=cache_system,
                    tag_aware=tag_aware,
                    tag_limit=tag_limit,
                )
        except Exception:
            logger.exception("judge_one_node crashed for disclosure %s", d.id)
            return {"findings": []}

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="judge") as ex:
        for res in ex.map(_one, disclosures):
            findings.extend(res.get("findings", []))

    return {"findings": findings}


def _record_completion(conn: psycopg.Connection, run_id: str) -> None:
    """Append one run_completions row for a completed run (best-effort).

    ON CONFLICT (run_id) DO NOTHING + UNIQUE(run_id) makes it idempotent under
    re-aggregation; user_id is denormalized from runs.created_by so the lifetime
    count survives report deletion.
    """
    try:
        owner = conn.execute("SELECT created_by FROM runs WHERE id=%s", (run_id,)).fetchone()
        user_id = owner["created_by"] if owner else None
        conn.execute(
            "INSERT INTO run_completions (run_id, user_id) VALUES (%s, %s) "
            "ON CONFLICT (run_id) DO NOTHING",
            (run_id, user_id),
        )
    except Exception:
        logger.warning("_record_completion failed; skipping count", exc_info=True)


def aggregate_node(
    state: dict,
    conn: psycopg.Connection,
    expected_disclosures: list[Disclosure] | None = None,
) -> dict:
    from accordance.api.cancellation import registry as cancel_registry
    from accordance.api.events import bus

    if cancel_registry.is_cancelled(state["run_id"]):
        conn.execute(
            "UPDATE runs SET status=%s, completed_at=CURRENT_TIMESTAMP WHERE id=%s",
            ("cancelled", state["run_id"]),
        )
        bus.publish(state["run_id"], {"type": "cancelled"})
        cancel_registry.clear(state["run_id"])
        return {"completed": True}

    cur = conn.execute(
        "UPDATE runs SET status=%s, completed_at=CURRENT_TIMESTAMP "
        "WHERE id=%s AND status != 'cancelled'",
        ("completed", state["run_id"]),
    )
    if cur.rowcount == 0:
        cancel_registry.clear(state["run_id"])
        return {"completed": True}

    if expected_disclosures:
        try:
            existing = {
                r["disclosure_id"]
                for r in conn.execute(
                    "SELECT disclosure_id FROM findings WHERE run_id=%s",
                    (state["run_id"],),
                ).fetchall()
            }
            missing = [d for d in expected_disclosures if d.id not in existing]
            for d in missing:
                conn.execute(
                    """
                    INSERT INTO findings
                        (run_id, disclosure_id, standard, status, note,
                         elements_json, suggested_fix)
                    VALUES (%s, %s, %s, 'error', %s, '[]', '')
                    ON CONFLICT (run_id, disclosure_id) DO NOTHING
                    """,
                    (
                        state["run_id"],
                        d.id,
                        d.standard,
                        "No verdict was persisted for this disclosure "
                        "(write failure or worker crash).",
                    ),
                )
            if missing:
                logger.warning(
                    "run %s: %d disclosure(s) had no persisted finding; recorded as errors: %s",
                    state["run_id"],
                    len(missing),
                    [d.id for d in missing],
                )
        except Exception:
            logger.warning(
                "run %s: finding reconciliation failed",
                state["run_id"],
                exc_info=True,
            )

    _record_completion(conn, state["run_id"])

    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM findings WHERE run_id=%s GROUP BY status",
        (state["run_id"],),
    ).fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    total = sum(counts.values())
    errored = counts.get("error", 0)
    logger.info(
        "run %s completed: %d findings, %d errored",
        state["run_id"],
        total,
        errored,
    )

    bus.publish(state["run_id"], {"type": "completed"})
    return {"completed": True}
