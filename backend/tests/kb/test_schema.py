import pytest
from pydantic import ValidationError

from accordance.kb.schema import Disclosure, RequiredElement


def test_disclosure_valid():
    d = Disclosure(
        id="303-3",
        standard="GRI 303: Water and Effluents 2018",
        title="Water withdrawal",
        category="topic",
        requirement_text="Total water withdrawal...",
        required_elements=[
            RequiredElement(id="total_withdrawal", desc="Total in megaliters"),
        ],
        retrieval_queries=["water withdrawal"],
        suggested_fix_template="Add a breakdown table.",
    )
    assert d.id == "303-3"
    assert len(d.required_elements) == 1


def test_disclosure_invalid_category():
    with pytest.raises(ValidationError):
        Disclosure(
            id="303-3",
            standard="GRI 303",
            title="x",
            category="invalid",  # type: ignore[arg-type]
            requirement_text="x",
            required_elements=[],
            retrieval_queries=["q"],
            suggested_fix_template="x",
        )
