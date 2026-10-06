"""Pure-function comparison of judge findings against ground truth.

No DB, no I/O. Feed it `(GroundTruth, list[FindingView])` and it returns
an EvalReport. This is the unit-testable core; the runner module wraps
it with DB + pipeline orchestration.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from accordance.eval.schema import GroundTruth, LabeledDisclosure, LabeledElement
from accordance.models import FindingView

DISCLOSURE_STATUS_LABELS = ("covered", "partial", "missing", "error", "not_judged")
ELEMENT_STATUS_LABELS = ("found", "partial", "missing", "not_judged")


class ElementEvalResult(BaseModel):
    element_id: str
    expected_status: str
    actual_status: str
    correct: bool
    expected_page: int | None = None
    actual_page: int | None = None


class DisclosureEvalResult(BaseModel):
    disclosure_id: str
    expected_status: str
    actual_status: str
    correct: bool
    expected_score: int | None = None
    actual_score: int | None = None
    score_exact: bool | None = None
    abs_error: int | None = None
    expected_evidence_page: int | None = None
    actual_evidence_page: int | None = None
    page_match: bool | None = None
    elements: list[ElementEvalResult]
    note: str | None = None
    evidence_excerpt: str | None = None
    retrieved_pages: list[int] = Field(default_factory=list)
    retrieval_hit: bool | None = None


class ClassMetrics(BaseModel):
    label: str
    support: int
    precision: float
    recall: float
    f1: float


class SystemConfig(BaseModel):
    """System configuration snapshot for the run that produced these findings.

    Pulled from `findings.prompt_hash` and `judge_traces` so an eval report
    can be attributed to a specific code state. When two eval reports
    differ, this section is the first place to look for *why*.
    """

    prompt_hashes: list[str] = []
    models: list[str] = []
    total_traces: int = 0
    rejudge_count: int = 0
    vision_fallback_count: int = 0
    hallucinated_cleared_count: int = 0
    no_excerpt_count: int = 0
    parse_fallback_count: int = 0
    parse_error_count: int = 0
    retrieval_mode: str = "hybrid"
    retrieval_per_element: bool = True
    rerank_enabled: bool = False
    rerank_model: str = ""
    rerank_top_n: int = 0


class EvalReport(BaseModel):
    report_id: str
    run_id: str | None = None
    total_disclosures_labeled: int
    correct_disclosures: int
    disclosure_accuracy: float
    total_elements_labeled: int
    correct_elements: int
    element_accuracy: float
    total_scored: int = 0
    score_exact_accuracy: float | None = None
    score_within_one_accuracy: float | None = None
    score_mae: float | None = None
    na_precision: float | None = None
    na_recall: float | None = None
    false_high: int = 0
    disclosure_confusion: dict[str, dict[str, int]]
    element_confusion: dict[str, dict[str, int]]
    disclosure_class_metrics: list[ClassMetrics]
    element_class_metrics: list[ClassMetrics]
    page_match_rate: float | None
    page_match_count: int
    page_match_total: int
    retrieval_recall: float | None = None
    retrieval_recall_count: int = 0
    retrieval_recall_total: int = 0
    not_judged: list[str]
    extra_findings: list[str]
    disclosure_results: list[DisclosureEvalResult]
    system_config: SystemConfig | None = None


def _empty_confusion(labels: tuple[str, ...]) -> dict[str, dict[str, int]]:
    return {row: {col: 0 for col in labels} for row in labels}


def _class_metrics(
    confusion: dict[str, dict[str, int]], labels: tuple[str, ...]
) -> list[ClassMetrics]:
    """Per-class precision / recall / F1.

    precision[c] = TP / (TP + FP)  where FP = items predicted c but expected != c
    recall[c]    = TP / (TP + FN)  where FN = items expected c but predicted != c
    """
    out: list[ClassMetrics] = []
    for c in labels:
        tp = confusion[c][c]
        fp = sum(confusion[r][c] for r in labels if r != c)
        fn = sum(confusion[c][col] for col in labels if col != c)
        support = tp + fn
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall)
            else 0.0
        )
        out.append(
            ClassMetrics(
                label=c, support=support, precision=precision, recall=recall, f1=f1
            )
        )
    return out


def _compare_elements(
    labeled: list[LabeledElement], finding: FindingView
) -> list[ElementEvalResult]:
    """Per-element comparison. We only score elements the labeler tagged."""
    by_id = {e.id: e for e in finding.elements}
    out: list[ElementEvalResult] = []
    for le in labeled:
        actual = by_id.get(le.id)
        actual_status = actual.status.value if actual else "not_judged"
        actual_page = actual.page if actual else None
        out.append(
            ElementEvalResult(
                element_id=le.id,
                expected_status=le.expected_status,
                actual_status=actual_status,
                correct=actual_status == le.expected_status,
                expected_page=le.expected_page,
                actual_page=actual_page,
            )
        )
    return out


def _compare_one_disclosure(
    labeled: LabeledDisclosure, finding: FindingView | None
) -> DisclosureEvalResult:
    if finding is None:
        elements = [
            ElementEvalResult(
                element_id=le.id,
                expected_status=le.expected_status,
                actual_status="not_judged",
                correct=False,
                expected_page=le.expected_page,
            )
            for le in labeled.elements
        ]
        exp = labeled.expected_score
        act = None
        score_exact = None if exp is None else (act is not None and act == exp)
        abs_error = None if (exp is None or act is None) else abs(act - exp)
        return DisclosureEvalResult(
            disclosure_id=labeled.id,
            expected_status=labeled.expected_status,
            actual_status="not_judged",
            correct=False,
            expected_score=exp,
            actual_score=act,
            score_exact=score_exact,
            abs_error=abs_error,
            expected_evidence_page=labeled.expected_evidence_page,
            page_match=None if labeled.expected_evidence_page is None else False,
            elements=elements,
        )

    actual_status = finding.status.value
    page_match: bool | None = None
    if labeled.expected_evidence_page is not None:
        page_match = (
            finding.evidence_page is not None
            and abs(finding.evidence_page - labeled.expected_evidence_page) <= 1
        )
    exp = labeled.expected_score
    act = finding.score
    score_exact = None if exp is None else (act is not None and act == exp)
    abs_error = None if (exp is None or act is None) else abs(act - exp)
    return DisclosureEvalResult(
        disclosure_id=labeled.id,
        expected_status=labeled.expected_status,
        actual_status=actual_status,
        correct=actual_status == labeled.expected_status,
        expected_score=exp,
        actual_score=act,
        score_exact=score_exact,
        abs_error=abs_error,
        expected_evidence_page=labeled.expected_evidence_page,
        actual_evidence_page=finding.evidence_page,
        page_match=page_match,
        elements=_compare_elements(labeled.elements, finding),
        note=finding.note,
        evidence_excerpt=finding.evidence_excerpt,
    )


def compute_eval(
    gt: GroundTruth,
    findings: list[FindingView],
    run_id: str | None = None,
    retrieved_pages_by_disclosure: dict[str, set[int]] | None = None,
) -> EvalReport:
    findings_by_id = {f.disclosure_id: f for f in findings}

    disclosure_results = [
        _compare_one_disclosure(d, findings_by_id.get(d.id)) for d in gt.disclosures
    ]

    rr_hits = 0
    rr_total = 0
    if retrieved_pages_by_disclosure is not None:
        gt_by_id = gt.by_id()
        for r in disclosure_results:
            pages = sorted(retrieved_pages_by_disclosure.get(r.disclosure_id, set()))
            r.retrieved_pages = pages
            expected = gt_by_id[r.disclosure_id].expected_evidence_page
            if expected is not None:
                rr_total += 1
                hit = any(abs(p - expected) <= 1 for p in pages)
                r.retrieval_hit = hit
                if hit:
                    rr_hits += 1

    disc_conf = _empty_confusion(DISCLOSURE_STATUS_LABELS)
    elem_conf = _empty_confusion(ELEMENT_STATUS_LABELS)
    correct_d = 0
    correct_e = 0
    total_e = 0
    page_hits = 0
    page_total = 0
    for r in disclosure_results:
        if r.expected_status in disc_conf and r.actual_status in disc_conf[r.expected_status]:
            disc_conf[r.expected_status][r.actual_status] += 1
        if r.correct:
            correct_d += 1
        if r.page_match is True:
            page_hits += 1
        if r.expected_evidence_page is not None:
            page_total += 1
        for er in r.elements:
            total_e += 1
            if (
                er.expected_status in elem_conf
                and er.actual_status in elem_conf[er.expected_status]
            ):
                elem_conf[er.expected_status][er.actual_status] += 1
            if er.correct:
                correct_e += 1

    not_judged = [r.disclosure_id for r in disclosure_results if r.actual_status == "not_judged"]
    labeled_ids = gt.disclosure_ids()
    extra = [f.disclosure_id for f in findings if f.disclosure_id not in labeled_ids]

    scored = [r for r in disclosure_results if r.expected_score is not None]
    total_scored = len(scored)
    n_exact = sum(
        1 for r in scored if r.actual_score is not None and r.actual_score == r.expected_score
    )
    n_within1 = sum(1 for r in scored if r.abs_error is not None and r.abs_error <= 1)
    errs = [r.abs_error for r in scored if r.abs_error is not None]
    pred_na = [r for r in scored if r.actual_score == 0]
    exp_na = [r for r in scored if r.expected_score == 0]
    tp_na = sum(1 for r in pred_na if r.expected_score == 0)
    false_high = sum(
        1 for r in scored
        if r.actual_score is not None and r.actual_score >= 4 and r.expected_score <= 2
    )
    score_exact_accuracy = (n_exact / total_scored) if total_scored else None
    score_within_one_accuracy = (n_within1 / total_scored) if total_scored else None
    score_mae = (sum(errs) / len(errs)) if errs else None
    na_precision = (tp_na / len(pred_na)) if pred_na else None
    na_recall = (tp_na / len(exp_na)) if exp_na else None

    total_d = len(disclosure_results)
    return EvalReport(
        report_id=gt.report_id,
        run_id=run_id,
        total_disclosures_labeled=total_d,
        correct_disclosures=correct_d,
        disclosure_accuracy=(correct_d / total_d) if total_d else 0.0,
        total_elements_labeled=total_e,
        correct_elements=correct_e,
        element_accuracy=(correct_e / total_e) if total_e else 0.0,
        total_scored=total_scored,
        score_exact_accuracy=score_exact_accuracy,
        score_within_one_accuracy=score_within_one_accuracy,
        score_mae=score_mae,
        na_precision=na_precision,
        na_recall=na_recall,
        false_high=false_high,
        disclosure_confusion=disc_conf,
        element_confusion=elem_conf,
        disclosure_class_metrics=_class_metrics(disc_conf, DISCLOSURE_STATUS_LABELS),
        element_class_metrics=_class_metrics(elem_conf, ELEMENT_STATUS_LABELS),
        page_match_rate=(page_hits / page_total) if page_total else None,
        page_match_count=page_hits,
        page_match_total=page_total,
        retrieval_recall=(rr_hits / rr_total) if rr_total else None,
        retrieval_recall_count=rr_hits,
        retrieval_recall_total=rr_total,
        not_judged=not_judged,
        extra_findings=extra,
        disclosure_results=disclosure_results,
    )


def coverage_gap(report: EvalReport) -> int:
    """Number of disclosures the labeler said were 'covered' but the judge missed
    (marked 'missing' or 'not_judged'). False-negatives are the dominant failure
    mode in current runs, so this is a useful headline metric.
    """
    conf = report.disclosure_confusion
    return conf["covered"]["missing"] + conf["covered"]["not_judged"]


def false_covered(report: EvalReport) -> int:
    """Disclosures the labeler said were 'missing' but the judge claimed 'covered'.
    Rare but bad — indicates hallucination of evidence.
    """
    return report.disclosure_confusion["missing"]["covered"]
