from accordance import db
from accordance.graph.nodes import (
    UsageRecord,
    _judge_usage_with_fallback,
    _persist_usage,
    _usage_records_from_callback,
)
from accordance.judge.core import JudgeTrace


def _trace(est_in=None, est_out=None, model="gpt-5-mini"):
    return JudgeTrace(
        chunk_ids=[],
        distances=[],
        pages=[],
        queries_used=[],
        parse_path="structured",
        error=None,
        latency_ms=1,
        prompt_hash="h",
        model_id=model,
        est_input_tokens=est_in,
        est_output_tokens=est_out,
    )


def test_persist_usage_writes_rows_with_owner_and_cost(monkeypatch):
    monkeypatch.setenv("MODEL_PRICES_JSON", '{"gpt-5-mini": {"in": 0.25, "out": 2.0}}')
    with db.connection() as conn:
        conn.execute("INSERT INTO users (username, password_hash) VALUES ('u', 'h')")
        uid = conn.execute("SELECT id FROM users WHERE username='u'").fetchone()["id"]
        conn.execute("INSERT INTO reports (id, name) VALUES ('rep', 'd.pdf')")
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status, created_by) "
            "VALUES ('run1','rep',1,'initial','d.pdf','s','/x.pdf','judging',%s)",
            (uid,),
        )

        _persist_usage(
            conn,
            "run1",
            [
                UsageRecord("judge", "gpt-5-mini", 1_000_000, 500_000),
                UsageRecord("embedding", "text-embedding-3-small", 1_000_000, 0),
            ],
        )

        rows = conn.execute(
            "SELECT kind, user_id, cost_usd FROM llm_usage WHERE run_id='run1' ORDER BY kind"
        ).fetchall()
        assert [r["kind"] for r in rows] == ["embedding", "judge"]
        assert all(r["user_id"] == uid for r in rows)
        judge = next(r for r in rows if r["kind"] == "judge")
        assert round(judge["cost_usd"], 6) == 1.25  # 0.25 + 1.00


def test_persist_usage_empty_records_is_noop():
    with db.connection() as conn:
        _persist_usage(conn, "missing-run", [])  # must not raise
        assert conn.execute("SELECT COUNT(*) AS n FROM llm_usage").fetchone()["n"] == 0


# ── cached input / cache writes ──────────────────────────────────────


def test_usage_records_capture_cache_read_and_creation():
    # LangChain nests the cache split under input_token_details, and
    # `input_tokens` is the TOTAL (cached included). Reading only the two
    # top-level fields billed every cache hit at the full input rate.
    md = {
        "gpt-5-mini": {
            "input_tokens": 10_000,
            "output_tokens": 400,
            "input_token_details": {"cache_read": 2_500, "cache_creation": 1_000},
        }
    }
    (rec,) = _usage_records_from_callback(md, "judge")
    assert rec.input_tokens == 10_000
    assert rec.cached_input_tokens == 2_500
    assert rec.cache_write_tokens == 1_000


def test_usage_records_default_cache_fields_to_zero_when_absent():
    md = {"gpt-5-mini": {"input_tokens": 10_000, "output_tokens": 400}}
    (rec,) = _usage_records_from_callback(md, "judge")
    assert rec.cached_input_tokens == 0
    assert rec.cache_write_tokens == 0


def test_judge_usage_fills_output_when_provider_reports_input_only():
    # The ABMM prod run: the proxy returned input tokens but a zero output
    # count. The old `if not judge_records` guard saw a non-empty list and
    # skipped the estimate, silently persisting output_tokens=0.
    md = {"gpt-5-mini": {"input_tokens": 11_000, "output_tokens": 0}}
    (rec,) = _judge_usage_with_fallback(md, [_trace(est_in=10_800, est_out=430)])
    assert rec.input_tokens == 11_000  # provider's real count wins
    assert rec.output_tokens == 430  # estimate fills the missing side


def test_judge_usage_prefers_provider_counts_over_estimates():
    md = {"gpt-5-mini": {"input_tokens": 11_000, "output_tokens": 3_400}}
    (rec,) = _judge_usage_with_fallback(md, [_trace(est_in=10_800, est_out=430)])
    assert rec.output_tokens == 3_400


def test_judge_usage_falls_back_entirely_when_callback_is_empty():
    (rec,) = _judge_usage_with_fallback({}, [_trace(est_in=10_800, est_out=430)])
    assert (rec.input_tokens, rec.output_tokens) == (10_800, 430)
    assert rec.kind == "judge"


def test_judge_usage_empty_when_no_metadata_and_no_estimates():
    assert _judge_usage_with_fallback({}, [_trace()]) == []
    assert _judge_usage_with_fallback({}, []) == []


def test_persist_usage_prices_cached_tokens_at_the_cached_rate(monkeypatch):
    monkeypatch.setenv(
        "MODEL_PRICES_JSON", '{"gpt-5-mini": {"in": 0.25, "cached": 0.025, "out": 2.0}}'
    )
    with db.connection() as conn:
        conn.execute("INSERT INTO reports (id, name) VALUES ('rep2', 'd.pdf')")
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status) "
            "VALUES ('run2','rep2',1,'initial','d.pdf','s','/x.pdf','judging')"
        )
        _persist_usage(
            conn,
            "run2",
            [UsageRecord("judge", "gpt-5-mini", 1_000_000, 0, cached_input_tokens=800_000)],
        )
        row = conn.execute(
            "SELECT input_tokens, cached_input_tokens, cost_usd "
            "FROM llm_usage WHERE run_id='run2'"
        ).fetchone()
        # 200k uncached @ $0.25/M = 0.05 ; 800k cached @ $0.025/M = 0.02
        assert row["input_tokens"] == 1_000_000
        assert row["cached_input_tokens"] == 800_000
        assert round(row["cost_usd"], 6) == 0.07


def test_usage_records_capture_flex_prefixed_cache_keys():
    """The flex tier renames the cache fields.

    Observed on OpenRouter/OpenAI flex: input_token_details carries
    `flex_cache_read` / `flex_cache_creation` instead of `cache_read` /
    `cache_creation`. Reading only the unprefixed names silently records
    cached=0 on every flex call, re-creating the 10x over-count this
    accounting was built to fix — and precisely on the tier chosen to save
    money.
    """
    md = {
        "openai/gpt-5.6-luna": {
            "input_tokens": 18_001,
            "output_tokens": 320,
            "input_token_details": {
                "audio": 0,
                "flex_cache_read": 17_998,
                "flex_cache_creation": 5,
                "flex": 3,
            },
        }
    }
    (rec,) = _usage_records_from_callback(md, "judge")
    assert rec.cached_input_tokens == 17_998
    assert rec.cache_write_tokens == 5


def test_usage_records_do_not_double_count_when_both_key_styles_appear():
    md = {
        "m": {
            "input_tokens": 100,
            "output_tokens": 1,
            "input_token_details": {"cache_read": 40, "flex_cache_read": 40},
        }
    }
    (rec,) = _usage_records_from_callback(md, "judge")
    assert rec.cached_input_tokens == 40


def test_persist_usage_applies_the_service_tier_multiplier(monkeypatch):
    """A flex run priced against the standard table over-counts 2x."""
    monkeypatch.setenv("MODEL_PRICES_JSON", '{"m": {"in": 0.20, "out": 1.20}}')
    with db.connection() as conn:
        conn.execute("INSERT INTO reports (id, name) VALUES ('rep3', 'd.pdf')")
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
            "pdf_sha256, pdf_path, status) "
            "VALUES ('run3','rep3',1,'initial','d.pdf','s','/x.pdf','judging')"
        )
        _persist_usage(
            conn,
            "run3",
            [
                UsageRecord("judge", "m", 1_000_000, 0, service_tier="flex"),
                # Embeddings are not tiered — they must stay at full price even
                # when the judge runs on flex.
                UsageRecord("embedding", "m", 1_000_000, 0),
            ],
        )
        rows = {
            r["kind"]: r["cost_usd"]
            for r in conn.execute(
                "SELECT kind, cost_usd FROM llm_usage WHERE run_id='run3'"
            ).fetchall()
        }
        assert round(rows["judge"], 6) == 0.10  # 0.20 * 0.5
        assert round(rows["embedding"], 6) == 0.20  # untouched
