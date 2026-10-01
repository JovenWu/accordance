from accordance.eval.metrics import compute_eval
from accordance.eval.schema import GroundTruth
from accordance.models import FindingView


def _gt(rows):
    return GroundTruth(
        report_id="t",
        pdf_filename="t.pdf",
        disclosures=[
            {"id": did, "expected_status": "covered", "expected_score": sc}
            for did, sc in rows
        ],
    )


def _finding(did: str, score: int | None) -> FindingView:
    return FindingView(
        disclosure_id=did, standard="GRI 2", status="covered", score=score,
        na_reason=None, note="", evidence_excerpt=None, evidence_page=None,
        elements=[], suggested_fix="", vision_fallback_used=False,
    )


def test_score_exact_and_within_one_and_mae():
    gt = _gt([("a", 5), ("b", 4), ("c", 1)])
    findings = [_finding("a", 5), _finding("b", 5), _finding("c", 1)]
    r = compute_eval(gt, findings)
    assert round(r.score_exact_accuracy, 3) == round(2 / 3, 3)
    assert r.score_within_one_accuracy == 1.0
    assert round(r.score_mae, 3) == round(1 / 3, 3)
    assert r.total_scored == 3


def test_na_precision_recall():
    gt = _gt([("a", 0), ("b", 0), ("c", 3)])
    findings = [_finding("a", 0), _finding("b", 3), _finding("c", 0)]
    r = compute_eval(gt, findings)
    assert r.na_precision == 0.5
    assert r.na_recall == 0.5


def test_false_high_guard():
    gt = _gt([("a", 1), ("b", 2), ("c", 5)])
    findings = [_finding("a", 5), _finding("b", 2), _finding("c", 5)]
    r = compute_eval(gt, findings)
    assert r.false_high == 1


def test_score_metrics_none_when_no_expected_score():
    gt = GroundTruth(
        report_id="t", pdf_filename="t.pdf",
        disclosures=[{"id": "a", "expected_status": "covered"}],
    )
    r = compute_eval(gt, [_finding("a", 5)])
    assert r.score_exact_accuracy is None
    assert r.total_scored == 0
