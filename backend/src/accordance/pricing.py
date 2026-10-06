"""LLM/embedding price table and cost computation (USD per 1M tokens).

Rates are configuration, not sourced constants — VERIFY against current provider
pricing before relying on the absolute $ figure. Unknown models cost 0 (logged),
so a missing entry visibly undercounts rather than crashing a run.
"""
import json
import logging

logger = logging.getLogger(__name__)

DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "gpt-5-mini": {"in": 0.25, "cached": 0.025, "out": 2.00},
    "gpt-5.4-mini": {"in": 0.75, "cached": 0.075, "out": 4.50},
    "gpt-5.6-luna": {"in": 0.20, "cached": 0.02, "cache_write": 0.25, "out": 1.20},
    "text-embedding-3-small": {"in": 0.02, "cached": 0.02, "out": 0.0},
}

_OPTIONAL_RATES = ("cached", "cache_write")

_TIER_MULTIPLIERS: dict[str, float] = {
    "": 1.0,
    "auto": 1.0,
    "default": 1.0,
    "standard": 1.0,
    "flex": 0.5,
}


def _tier_multiplier(service_tier: str) -> float:
    tier = (service_tier or "").strip().lower()
    if tier in _TIER_MULTIPLIERS:
        return _TIER_MULTIPLIERS[tier]
    logger.warning(
        "service tier %r has no pricing multiplier; billing at the standard "
        "rate. If this tier is not full price the recorded cost is wrong.",
        service_tier,
    )
    return 1.0


def _is_rate(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _valid_price_entry(v: object) -> bool:
    """A price entry must be a dict carrying numeric `in` AND `out` rates.

    Anything else (a bare number, a dict missing a side) is rejected so it can
    never reach cost_usd and raise KeyError — the bug that silently zeroed every
    llm_usage row for a run when a partial MODEL_PRICES_JSON override slipped in.

    `cached`/`cache_write` are optional, but when supplied must be numeric too.
    """
    if not isinstance(v, dict) or not _is_rate(v.get("in")) or not _is_rate(v.get("out")):
        return False
    return all(_is_rate(v[k]) for k in _OPTIONAL_RATES if k in v)


def load_prices(settings) -> dict[str, dict[str, float]]:
    """DEFAULT_PRICES merged with the optional MODEL_PRICES_JSON env override.

    The override is validated entry-by-entry: malformed entries are warned about
    and skipped (the rest still apply), so a single typo can't poison the table.
    """
    prices = {k: dict(v) for k, v in DEFAULT_PRICES.items()}
    raw = (getattr(settings, "model_prices_json", "") or "").strip()
    if not raw:
        return prices
    try:
        override = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("MODEL_PRICES_JSON is not valid JSON; using defaults")
        return prices
    if not isinstance(override, dict):
        logger.warning("MODEL_PRICES_JSON must be a JSON object; using defaults")
        return prices
    for model, entry in override.items():
        if _valid_price_entry(entry):
            merged = {"in": float(entry["in"]), "out": float(entry["out"])}
            for k in _OPTIONAL_RATES:
                if k in entry:
                    merged[k] = float(entry[k])
            prices[model] = merged
        else:
            logger.warning(
                "MODEL_PRICES_JSON entry for %r is malformed "
                "(need {\"in\": <num>, \"out\": <num>}); skipping it",
                model,
            )
    return prices


def _candidate_forms(model: str) -> list[str]:
    bare = model.rsplit(":", 1)[-1]
    forms = [bare]
    if "/" in bare:
        forms.append(bare.split("/", 1)[-1])
    return forms


def _match_key(model: str, prices: dict) -> str | None:
    candidates = [
        k
        for k in prices
        for form in _candidate_forms(model)
        if form == k or form.startswith(k)
    ]
    return max(candidates, key=len) if candidates else None


def model_is_priced(model: str, prices: dict | None = None) -> bool:
    """True if `model` resolves to a price entry (used for a startup warning)."""
    table = prices if prices is not None else DEFAULT_PRICES
    return _match_key(model, table) is not None


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    prices: dict | None = None,
    *,
    cached_tokens: int = 0,
    cache_write_tokens: int = 0,
    service_tier: str = "",
) -> float:
    """USD cost of a single call. Unknown model -> 0.0 + a warning.

    ``input_tokens`` is the TOTAL prompt size — the convention OpenAI and
    LangChain both use — and ``cached_tokens``/``cache_write_tokens`` are
    SUBSETS of it, billed at their own rates. Billing a cache hit at the full
    input rate over-counts it ~10x, which is what this split fixes.

    Uses .get(...) for the rates so a partial entry that somehow reaches here
    degrades to 0 for the missing side instead of raising. A missing cache rate
    falls back to the input rate: over-counting is the safe direction.
    """
    table = prices if prices is not None else DEFAULT_PRICES
    key = _match_key(model, table)
    if key is None:
        logger.warning("no price entry for model %r; recording cost 0", model)
        return 0.0
    p = table[key]
    rate_in = p.get("in", 0.0) or 0.0
    rate_out = p.get("out", 0.0) or 0.0
    rate_cached = p["cached"] if _is_rate(p.get("cached")) else rate_in
    rate_write = p["cache_write"] if _is_rate(p.get("cache_write")) else rate_in

    if cached_tokens + cache_write_tokens > input_tokens:
        logger.warning(
            "%s reported cached=%d + cache_write=%d exceeding input_tokens=%d; "
            "the split is inconsistent, so the recorded cost is unreliable. "
            "Reconcile against the provider's own invoice.",
            model,
            cached_tokens,
            cache_write_tokens,
            input_tokens,
        )
    uncached = max(0, input_tokens - cached_tokens - cache_write_tokens)
    return (
        (
            uncached * rate_in
            + cached_tokens * rate_cached
            + cache_write_tokens * rate_write
            + output_tokens * rate_out
        )
        * _tier_multiplier(service_tier)
        / 1_000_000
    )
