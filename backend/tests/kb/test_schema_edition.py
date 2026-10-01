import pytest
from pydantic import ValidationError

from accordance.kb.schema import Disclosure

BASE = dict(
    id="x-1", standard="GRI X", title="t", category="topic",
    requirement_text="r",
    required_elements=[{"id": "a", "desc": "d"}],
    retrieval_queries=["q"],
    suggested_fix_template="f",
)

def test_edition_fields_default_to_current():
    d = Disclosure(**BASE)
    assert d.status == "current"
    assert d.effective_date is None
    assert d.effective_until is None
    assert d.superseded_by is None

def test_edition_fields_parse():
    d = Disclosure(**{**BASE, "status": "superseded",
                      "effective_until": "2025-12-31",
                      "superseded_by": "GRI 101: Biodiversity 2024"})
    assert d.status == "superseded"
    assert d.superseded_by == "GRI 101: Biodiversity 2024"

def test_sector_category_allowed():
    d = Disclosure(**{**BASE, "category": "sector"})
    assert d.category == "sector"

def test_bad_status_rejected():
    with pytest.raises(ValidationError):
        Disclosure(**{**BASE, "status": "retired"})
