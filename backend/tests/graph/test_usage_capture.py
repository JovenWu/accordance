from accordance.graph.nodes import _usage_records_from_callback


def test_usage_records_from_callback_maps_models_to_records():
    usage_md = {
        "gpt-5-mini-2025-08-07": {"input_tokens": 1200, "output_tokens": 300},
    }
    recs = _usage_records_from_callback(usage_md, "judge")
    assert len(recs) == 1
    assert recs[0].kind == "judge"
    assert recs[0].model == "gpt-5-mini-2025-08-07"
    assert recs[0].input_tokens == 1200
    assert recs[0].output_tokens == 300


def test_usage_records_from_callback_empty_is_empty():
    assert _usage_records_from_callback({}, "vision") == []
    assert _usage_records_from_callback(None, "judge") == []


def test_estimate_tokens_is_positive():
    from accordance.judge.core import _estimate_tokens

    assert _estimate_tokens("hello world, this is a sustainability report") > 0
    assert _estimate_tokens("") == 0
