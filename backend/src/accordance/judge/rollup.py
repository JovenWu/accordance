"""Deterministic disclosure grading: per-element verdicts -> a 0-5 score.

0 = Not Applicable, 1 = Missing ... 5 = Complete. The LLM judges each element
(found/partial/missing) and flags applicability; the *grade* is computed here,
not taken from the LLM's holistic status. This removes the over-conservative
covered->partial collapse (one "partial" element no longer forces the whole
disclosure down — it yields a 4, "substantial").
"""

from __future__ import annotations

from accordance.judge.output_schema import ElementJudgment, ElementStatus

NO_OMISSION_DISCLOSURES = frozenset(
    {"2-1", "2-2", "2-3", "2-4", "2-5", "3-1", "3-2"}
)

_ELEMENT_WEIGHT = {
    ElementStatus.found: 1.0,
    ElementStatus.partial: 0.5,
    ElementStatus.missing: 0.0,
}


def compute_score(
    elements: list[ElementJudgment],
    applicable: bool,
    disclosure_id: str,
    *,
    status: str | None = None,
    cutoff_low: float = 0.33,
    cutoff_high: float = 0.66,
) -> int:
    """Map per-element verdicts to a 0-5 grade.

    0 = Not Applicable (only when `applicable` is False AND the disclosure may
    be omitted). Otherwise bin f = mean element weight (found=1, partial=0.5,
    missing=0) into 1..5.

    ``status`` is the judge's holistic verdict ("covered"/"partial"/"missing").
    It is used ONLY as a fallback when ``elements`` is empty: the schema permits
    an empty elements array and the markdown-fence parse path can validate a
    response that omits it, so a disclosure the model judged "covered" could
    otherwise collapse to a 1 (Missing) — a grade that contradicts the stored
    status and silently drags down the coverage score. When elements are
    present they remain authoritative and ``status`` is ignored.
    """
    if not applicable and disclosure_id not in NO_OMISSION_DISCLOSURES:
        return 0
    if not elements:
        if status is not None:
            backmapped = score_from_legacy_status(status)
            if backmapped is not None:
                return backmapped
        return 1
    f = sum(_ELEMENT_WEIGHT[e.status] for e in elements) / len(elements)
    if f <= 0.0:
        return 1
    if f <= cutoff_low:
        return 2
    if f <= cutoff_high:
        return 3
    if f < 1.0:
        return 4
    return 5


def score_from_legacy_status(status: str) -> int | None:
    """Back-map a pre-0-5 finding (covered/partial/missing/error) to a 0-5
    score for display. Returns None for 'error' / unknown."""
    return {"covered": 5, "partial": 3, "missing": 1}.get(status)


def effective_score(row) -> int | None:
    """The 0-5 grade for a findings row: the explicit `score` when present,
    else back-mapped from the legacy `status`. Accepts any mapping with
    "score"/"status" keys (psycopg dict-row or dict)."""
    s = row["score"]
    return s if s is not None else score_from_legacy_status(row["status"])
