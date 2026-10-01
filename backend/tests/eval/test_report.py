"""Smoke tests for markdown rendering."""

from accordance.eval.metrics import compute_eval
from accordance.eval.report import render_console_summary, render_markdown
from accordance.eval.schema import GroundTruth, LabeledDisclosure
from accordance.models import FindingView


def _gt(disclosures):
    return GroundTruth(
        report_id="demo", pdf_filename="demo.pdf", disclosures=disclosures
    )


def _finding(disc_id, status):
    return FindingView(
        disclosure_id=disc_id,
        standard="GRI 2",
        status=status,
        note="judge note here",
        evidence_excerpt=None,
        evidence_page=None,
        elements=[],
        suggested_fix="-",
        vision_fallback_used=False,
    )


def test_render_markdown_contains_expected_sections():
    gt = _gt(
        [
            LabeledDisclosure(id="2-1", expected_status="covered"),
            LabeledDisclosure(id="3-1", expected_status="missing"),
        ]
    )
    findings = [_finding("2-1", "partial"), _finding("3-1", "missing")]
    report = compute_eval(gt, findings, run_id="abc-123")
    md = render_markdown(report)

    assert "# Eval Report: `demo`" in md
    assert "Run ID:** `abc-123`" in md
    assert "## Headline" in md
    assert "## Disclosure Confusion Matrix" in md
    assert "Per-Class Metrics" in md
    # one mismatch (2-1)
    assert "## Mismatches (1)" in md
    assert "`2-1`: expected `covered`, got `partial`" in md


def test_render_markdown_omits_mismatch_section_when_perfect():
    gt = _gt([LabeledDisclosure(id="2-1", expected_status="covered")])
    report = compute_eval(gt, [_finding("2-1", "covered")])
    md = render_markdown(report)
    assert "## Mismatches" not in md


def test_console_summary_is_short_and_includes_run():
    gt = _gt([LabeledDisclosure(id="2-1", expected_status="covered")])
    report = compute_eval(gt, [_finding("2-1", "covered")], run_id="r1")
    s = render_console_summary(report)
    assert "Eval: demo" in s
    assert "run r1" in s
    assert s.count("\n") < 10  # roughly 1 screen


def test_render_includes_retrieval_recall():
    gt = GroundTruth(
        report_id="t",
        pdf_filename="t.pdf",
        disclosures=[
            LabeledDisclosure(id="2-1", expected_status="covered", expected_evidence_page=10)
        ],
    )
    findings = [
        FindingView(
            disclosure_id="2-1",
            standard="GRI 2",
            status="covered",
            note="-",
            evidence_excerpt=None,
            evidence_page=10,
            elements=[],
            suggested_fix="-",
            vision_fallback_used=False,
        )
    ]
    report = compute_eval(gt, findings, retrieved_pages_by_disclosure={"2-1": {10}})
    md = render_markdown(report)
    assert "Retrieval recall" in md


def test_mismatch_block_shows_retrieved_pages():
    gt = GroundTruth(
        report_id="t",
        pdf_filename="t.pdf",
        disclosures=[
            LabeledDisclosure(id="2-1", expected_status="covered", expected_evidence_page=10)
        ],
    )
    findings = [FindingView(disclosure_id="2-1", standard="GRI 2", status="partial",
                            note="-", evidence_excerpt=None, evidence_page=9,
                            elements=[], suggested_fix="-", vision_fallback_used=False)]
    report = compute_eval(gt, findings, retrieved_pages_by_disclosure={"2-1": {9, 10}})
    md = render_markdown(report)
    assert "surfaced pages [9, 10]" in md
    assert "✅" in md
