# backend/tests/kb/test_kb_content.py
from pathlib import Path

from accordance.kb.loader import load_kb

REPO_ROOT = Path(__file__).resolve().parents[3]
KB = load_kb(REPO_ROOT / "kb" / "gri")

def test_102_titles_match_official():
    assert KB["102-2"].title == "Climate change adaptation plan"
    assert KB["102-9"].title == "GHG removals in the value chain"

def test_102_3_is_quantitative_just_transition():
    elems = {e.id for e in KB["102-3"].required_elements}
    # quantitative metrics, not a narrative approach
    assert "workers_recruited_terminated_redeployed" in elems
    assert "employees_reskilled" in elems

def test_102_emissions_cross_reference_gri103():
    # Scope 1/2/3 must reference GRI 103 energy disclosures
    assert "103-2-a" in KB["102-5"].requirement_text
    assert "103-2-b" in KB["102-6"].requirement_text
    assert "103-3-a" in KB["102-7"].requirement_text

def test_103_1_has_impacts_element():
    elems = {e.id for e in KB["103-1"].required_elements}
    assert "impacts_on_economy_environment_people" in elems

def test_3_1_requires_sector_standards():
    txt = KB["3-1"].requirement_text.lower()
    assert "sector standard" in txt

def test_14_8_4_all_three_closure_statuses():
    elems = {e.id for e in KB["14.8.4"].required_elements}
    assert {"has_plan_in_place", "undergoing_activities",
            "closed_and_rehabilitated"} <= elems

def test_14_8_6_is_land_disturbed_rehabilitated():
    assert KB["14.8.6"].title == "Land disturbed and rehabilitated"
    elems = {e.id for e in KB["14.8.6"].required_elements}
    assert {"land_disturbed_not_rehabilitated_ha",
            "land_disturbed_and_rehabilitated_ha"} <= elems
