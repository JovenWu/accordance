import pytest
import yaml
from pydantic import ValidationError

from accordance.eval.bootstrap import _slugify, render_ground_truth
from accordance.eval.schema import GroundTruth


def _row(**kw):
    base = {"id": "run-1", "pdf_filename": "Contoh VALE 2024.pdf", "pdf_sha256": "abc123"}
    base.update(kw)
    return base


def _finding(disc_id, status, *, note="", excerpt="", page=None, elements_json="[]"):
    return {
        "disclosure_id": disc_id,
        "status": status,
        "note": note,
        "evidence_excerpt": excerpt,
        "evidence_page": page,
        "elements_json": elements_json,
    }


def test_slugify():
    assert _slugify("Contoh VALE 2024.pdf") == "contoh-vale-2024"


def test_render_parses_and_mirrors_findings():
    findings = [
        _finding(
            "2-1", "partial", note="HQ on p4", page=4,
            elements_json='[{"id":"legal_name","status":"found","page":4},'
                          '{"id":"hq","status":"missing","page":null}]',
        ),
        _finding("303-3", "missing", note="no water table"),
    ]
    text = render_ground_truth(_row(), findings, blank_status=False)
    gt = GroundTruth.model_validate(yaml.safe_load(text))
    assert gt.report_id == "contoh-vale-2024"
    assert gt.pdf_sha256 == "abc123"
    by = gt.by_id()
    assert by["2-1"].expected_status == "partial"
    assert by["2-1"].expected_evidence_page == 4
    assert by["2-1"].elements[0].id == "legal_name"
    assert by["2-1"].elements[0].expected_status == "found"
    assert by["303-3"].expected_status == "missing"


def test_error_findings_are_commented_out():
    findings = [_finding("2-2", "error", note="boom")]
    text = render_ground_truth(_row(), findings, blank_status=False)
    data = yaml.safe_load(text)
    assert all(d["id"] != "2-2" for d in data["disclosures"]) or data["disclosures"] == []


def test_blank_status_emits_unfilled_sentinel():
    findings = [_finding("2-1", "partial", page=4)]
    text = render_ground_truth(_row(), findings, blank_status=True)
    assert "FILL_ME" in text
    with pytest.raises(ValidationError):
        GroundTruth.model_validate(yaml.safe_load(text))


def test_render_escapes_special_chars_and_strips_control_bytes():
    findings = [
        _finding(
            "2-1", "covered",
            note='He said "hi"\twith a tab and a \x00 NUL byte',
            excerpt="line one\nline two with a back\\slash",
            page=1,
        )
    ]
    text = render_ground_truth(_row(), findings, blank_status=False)
    gt = GroundTruth.model_validate(yaml.safe_load(text))
    notes = gt.by_id()["2-1"].notes
    assert notes is not None
    assert "\x00" not in notes
    assert "\t" not in notes
    assert '"hi"' in notes
