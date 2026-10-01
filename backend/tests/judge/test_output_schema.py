import pytest
from pydantic import ValidationError

from accordance.judge.output_schema import ElementStatus, JudgeOutput


def test_judge_output_parses_valid():
    raw = {
        "status": "partial",
        "elements": [
            {"id": "total", "status": "found", "page": 41},
            {"id": "breakdown", "status": "missing", "page": None},
        ],
        "note": "Total reported, breakdown missing.",
        "evidence_excerpt": "Total water withdrawn was 41 ML.",
        "evidence_page": 41,
        "needs_vision_fallback": False,
    }
    out = JudgeOutput.model_validate(raw)
    assert out.status == "partial"
    assert out.elements[0].status == ElementStatus.found


def test_judge_output_rejects_bad_status():
    with pytest.raises(ValidationError):
        JudgeOutput.model_validate({"status": "maybe", "elements": [], "note": "x"})


def test_judge_output_applicable_defaults_true():
    out = JudgeOutput.model_validate(
        {"status": "missing", "elements": [], "note": "x"}
    )
    assert out.applicable is True
    assert out.na_reason is None


def test_judge_output_accepts_not_applicable():
    out = JudgeOutput.model_validate(
        {
            "status": "missing",
            "elements": [],
            "note": "x",
            "applicable": False,
            "na_reason": "No such operations in scope.",
        }
    )
    assert out.applicable is False
    assert out.na_reason == "No such operations in scope."
