import pytest

from accordance.config import Settings
from accordance.pricing import cost_usd, load_prices, model_is_priced

PRICES = {
    "gpt-5-mini": {"in": 0.25, "out": 2.00},
    "text-embedding-3-small": {"in": 0.02, "out": 0.0},
}


def test_cost_usd_math():
    assert cost_usd("gpt-5-mini", 1_000_000, 500_000, PRICES) == 1.25


def test_cost_usd_strips_provider_prefix_and_dated_snapshot():
    assert cost_usd("openai:gpt-5-mini-2025-08-07", 1_000_000, 0, PRICES) == 0.25


def test_cost_usd_unknown_model_is_zero():
    from unittest.mock import patch

    with patch("accordance.pricing.logger") as mock_logger:
        assert cost_usd("mystery-model", 1_000_000, 1_000_000, PRICES) == 0.0
    assert mock_logger.warning.called
    assert "mystery-model" in str(mock_logger.warning.call_args)


def test_load_prices_merges_env_override():
    s = Settings(model_prices_json='{"gpt-5-mini": {"in": 1.0, "out": 1.0}}')
    merged = load_prices(s)
    assert merged["gpt-5-mini"] == {"in": 1.0, "out": 1.0}
    assert "text-embedding-3-small" in merged


def test_load_prices_skips_malformed_override_entry():
    s = Settings(model_prices_json='{"gpt-5-mini": {"in": 0.3}, "junk": 5}')
    merged = load_prices(s)
    assert merged["gpt-5-mini"] == {"in": 0.25, "cached": 0.025, "out": 2.00}
    assert "junk" not in merged


def test_cost_usd_tolerates_partial_price_entry():
    table = {"weird": {"in": 0.5}}
    assert cost_usd("weird", 1_000_000, 1_000_000, table) == 0.5


def test_cost_usd_matches_model_with_provider_path_prefix():
    table = {"gpt-5.4-mini": {"in": 0.25, "out": 2.0}}
    assert cost_usd("openai:cx/gpt-5.4-mini", 1_000_000, 1_000_000, table) == 2.25


def test_model_is_priced_detects_unpriced_model():
    table = {"gpt-5-mini": {"in": 0.25, "out": 2.0}}
    assert model_is_priced("openai:gpt-5-mini-2025-08-07", table) is True
    assert model_is_priced("openai:cx/gpt-5.4-mini", table) is False


CACHED_PRICES = {"m": {"in": 0.20, "cached": 0.02, "cache_write": 0.25, "out": 1.20}}


def test_cost_usd_bills_cached_tokens_at_the_cached_rate():
    assert cost_usd("m", 1_000_000, 0, CACHED_PRICES, cached_tokens=500_000) == 0.11


def test_cost_usd_bills_cache_writes_at_the_write_rate():
    assert cost_usd("m", 1_000_000, 0, CACHED_PRICES, cache_write_tokens=400_000) == 0.22


def test_cost_usd_cached_and_written_and_output_together():
    got = cost_usd(
        "m", 1_000_000, 500_000, CACHED_PRICES, cached_tokens=700_000, cache_write_tokens=100_000
    )
    assert got == pytest.approx(0.04 + 0.014 + 0.025 + 0.60)


def test_cost_usd_missing_cached_rate_falls_back_to_input_rate():
    table = {"m": {"in": 0.20, "out": 1.20}}
    assert cost_usd("m", 1_000_000, 0, table, cached_tokens=500_000) == 0.20


def test_cost_usd_without_cache_args_is_unchanged():
    assert cost_usd("m", 1_000_000, 1_000_000, CACHED_PRICES) == 0.20 + 1.20


def test_cost_usd_clamps_cache_tokens_exceeding_input():
    got = cost_usd("m", 100_000, 0, CACHED_PRICES, cached_tokens=500_000)
    assert got == 500_000 * 0.02 / 1_000_000


def test_load_prices_accepts_optional_cached_and_cache_write_rates():
    s = Settings(
        model_prices_json='{"m": {"in": 0.2, "cached": 0.02, "cache_write": 0.25, "out": 1.2}}'
    )
    merged = load_prices(s)
    assert merged["m"] == {"in": 0.2, "cached": 0.02, "cache_write": 0.25, "out": 1.2}


def test_load_prices_still_requires_in_and_out():
    s = Settings(model_prices_json='{"m": {"cached": 0.02, "cache_write": 0.25}}')
    assert "m" not in load_prices(s)


def test_default_prices_carry_cached_rates():
    from accordance.pricing import DEFAULT_PRICES

    assert DEFAULT_PRICES["gpt-5-mini"]["cached"] == 0.025


def test_flex_halves_every_rate():
    p = {"m": {"in": 0.20, "cached": 0.02, "cache_write": 0.25, "out": 1.20}}
    full = cost_usd("m", 1_000_000, 1_000_000, p, cached_tokens=200_000, cache_write_tokens=300_000)
    flex = cost_usd(
        "m", 1_000_000, 1_000_000, p,
        cached_tokens=200_000, cache_write_tokens=300_000, service_tier="flex",
    )
    assert flex == pytest.approx(full * 0.5)


def test_blank_and_default_tiers_are_full_price():
    p = {"m": {"in": 0.20, "out": 1.20}}
    full = cost_usd("m", 1_000_000, 0, p)
    assert cost_usd("m", 1_000_000, 0, p, service_tier="") == full
    assert cost_usd("m", 1_000_000, 0, p, service_tier="default") == full
    assert cost_usd("m", 1_000_000, 0, p, service_tier="auto") == full


def test_unmodelled_tier_is_not_silently_discounted():
    """'priority' costs MORE than standard. Guessing a multiplier would
    understate it, so it stays at 1.0 and warns rather than inventing a rate."""
    from unittest.mock import patch

    p = {"m": {"in": 0.20, "out": 1.20}}
    with patch("accordance.pricing.logger") as log:
        got = cost_usd("m", 1_000_000, 0, p, service_tier="priority")
    assert got == cost_usd("m", 1_000_000, 0, p)
    assert log.warning.called
    assert "priority" in str(log.warning.call_args)
