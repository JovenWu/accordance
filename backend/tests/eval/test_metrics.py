"""Pure-function tests for the eval metrics."""

from accordance.eval.metrics import (
    compute_eval,
    coverage_gap,
    false_covered,
)
from accordance.eval.schema import GroundTruth, LabeledDisclosure, LabeledElement
from accordance.judge.output_schema import ElementJudgment
from accordance.models import FindingView


def _gt(disclosures):
    return GroundTruth(
        report_id="t", pdf_filename="t.pdf", disclosures=disclosures
    )


def _finding(disc_id, status, *, elements=None, page=None, note="-"):
    return FindingView(
        disclosure_id=disc_id,
        standard="GRI 2",
        status=status,
        note=note,
        evidence_excerpt=None,
        evidence_page=page,
        elements=elements or [],
        suggested_fix="-",
        vision_fallback_used=False,
    )


def test_perfect_score():
    gt = _gt(
        [
            LabeledDisclosure(id="2-1", expected_status="covered"),
            LabeledDisclosure(id="3-1", expected_status="missing"),
        ]
    )
    findings = [
        _finding("2-1", "covered"),
        _finding("3-1", "missing"),
    ]
    r = compute_eval(gt, findings)
    assert r.disclosure_accuracy == 1.0
    assert r.correct_disclosures == 2
    assert r.disclosure_confusion["covered"]["covered"] == 1
    assert r.disclosure_confusion["missing"]["missing"] == 1


def test_complete_miss():
    gt = _gt([LabeledDisclosure(id="2-1", expected_status="covered")])
    findings = [_finding("2-1", "missing")]
    r = compute_eval(gt, findings)
    assert r.disclosure_accuracy == 0.0
    assert r.disclosure_confusion["covered"]["missing"] == 1
    assert coverage_gap(r) == 1
    assert false_covered(r) == 0


def test_not_judged_when_finding_missing():
    gt = _gt(
        [
            LabeledDisclosure(id="2-1", expected_status="covered"),
            LabeledDisclosure(id="3-1", expected_status="missing"),
        ]
    )
    findings = [_finding("2-1", "covered")]  # 3-1 never judged
    r = compute_eval(gt, findings)
    assert r.not_judged == ["3-1"]
    assert r.disclosure_confusion["missing"]["not_judged"] == 1


def test_element_accuracy():
    gt = _gt(
        [
            LabeledDisclosure(
                id="2-1",
                expected_status="partial",
                elements=[
                    LabeledElement(id="legal_name", expected_status="found"),
                    LabeledElement(id="hq", expected_status="found"),
                    LabeledElement(id="countries", expected_status="missing"),
                ],
            )
        ]
    )
    findings = [
        _finding(
            "2-1",
            "partial",
            elements=[
                ElementJudgment(id="legal_name", status="found", page=1),
                ElementJudgment(id="hq", status="missing", page=None),
                ElementJudgment(id="countries", status="missing", page=None),
            ],
        )
    ]
    r = compute_eval(gt, findings)
    assert r.total_elements_labeled == 3
    assert r.correct_elements == 2  # legal_name + countries
    assert r.element_accuracy == 2 / 3


def test_page_match_within_one():
    gt = _gt(
        [
            LabeledDisclosure(
                id="2-1", expected_status="covered", expected_evidence_page=10
            ),
            LabeledDisclosure(
                id="3-1", expected_status="covered", expected_evidence_page=20
            ),
            LabeledDisclosure(
                id="3-2", expected_status="covered", expected_evidence_page=30
            ),
        ]
    )
    findings = [
        _finding("2-1", "covered", page=10),  # exact
        _finding("3-1", "covered", page=21),  # ±1
        _finding("3-2", "covered", page=35),  # miss
    ]
    r = compute_eval(gt, findings)
    assert r.page_match_total == 3
    assert r.page_match_count == 2


def test_false_covered_detected():
    gt = _gt([LabeledDisclosure(id="2-1", expected_status="missing")])
    findings = [_finding("2-1", "covered")]
    r = compute_eval(gt, findings)
    assert false_covered(r) == 1


def test_extra_findings_not_penalized():
    gt = _gt([LabeledDisclosure(id="2-1", expected_status="covered")])
    findings = [
        _finding("2-1", "covered"),
        _finding("3-1", "missing"),  # not in gt
        _finding("3-2", "missing"),
    ]
    r = compute_eval(gt, findings)
    assert r.disclosure_accuracy == 1.0
    assert set(r.extra_findings) == {"3-1", "3-2"}


def test_class_metrics_precision_recall():
    # 3 covered (all correctly hit), 2 missing (one hit, one false-covered)
    gt = _gt(
        [
            LabeledDisclosure(id="a", expected_status="covered"),
            LabeledDisclosure(id="b", expected_status="covered"),
            LabeledDisclosure(id="c", expected_status="covered"),
            LabeledDisclosure(id="d", expected_status="missing"),
            LabeledDisclosure(id="e", expected_status="missing"),
        ]
    )
    findings = [
        _finding("a", "covered"),
        _finding("b", "covered"),
        _finding("c", "covered"),
        _finding("d", "covered"),  # FP for covered, FN for missing
        _finding("e", "missing"),
    ]
    r = compute_eval(gt, findings)
    cov = next(m for m in r.disclosure_class_metrics if m.label == "covered")
    miss = next(m for m in r.disclosure_class_metrics if m.label == "missing")
    # covered: TP=3, FP=1 (d), FN=0 -> P=0.75, R=1.0
    assert abs(cov.precision - 0.75) < 1e-9
    assert cov.recall == 1.0
    # missing: TP=1, FP=0, FN=1 -> P=1.0, R=0.5
    assert miss.precision == 1.0
    assert miss.recall == 0.5


def test_retrieval_recall_from_pages():
    gt = _gt(
        [
            LabeledDisclosure(id="2-1", expected_status="covered", expected_evidence_page=10),
            LabeledDisclosure(id="3-1", expected_status="covered", expected_evidence_page=50),
            LabeledDisclosure(id="3-2", expected_status="covered"),  # no page → not counted
        ]
    )
    findings = [_finding("2-1", "covered"), _finding("3-1", "covered"), _finding("3-2", "covered")]
    retrieved = {"2-1": {9, 30}, "3-1": {12, 13}, "3-2": {1}}  # 2-1 hits (10±1=9), 3-1 misses
    r = compute_eval(gt, findings, retrieved_pages_by_disclosure=retrieved)
    assert r.retrieval_recall_total == 2
    assert r.retrieval_recall_count == 1
    assert r.retrieval_recall == 0.5
    res = {d.disclosure_id: d for d in r.disclosure_results}
    assert res["2-1"].retrieval_hit is True
    assert res["3-1"].retrieval_hit is False
    assert res["3-2"].retrieval_hit is None  # no expected page
    assert res["2-1"].retrieved_pages == [9, 30]


def test_retrieval_recall_none_when_not_provided():
    gt = _gt([LabeledDisclosure(id="2-1", expected_status="covered", expected_evidence_page=10)])
    r = compute_eval(gt, [_finding("2-1", "covered")])
    assert r.retrieval_recall is None
    assert r.retrieval_recall_total == 0


def test_system_config_has_rerank_fields():
    from accordance.eval.metrics import SystemConfig

    sc = SystemConfig(rerank_enabled=True, rerank_model="ms-marco-MultiBERT-L-12", rerank_top_n=15)
    assert sc.rerank_enabled is True
    assert sc.rerank_model == "ms-marco-MultiBERT-L-12"
    assert sc.rerank_top_n == 15
