from accordance.judge.output_schema import ElementJudgment, ElementStatus
from accordance.judge.rollup import (
    NO_OMISSION_DISCLOSURES,
    compute_score,
    score_from_legacy_status,
)


def _els(*statuses: ElementStatus) -> list[ElementJudgment]:
    return [ElementJudgment(id=f"e{i}", status=s) for i, s in enumerate(statuses)]


F = ElementStatus.found
P = ElementStatus.partial
M = ElementStatus.missing


def test_all_found_is_5():
    assert compute_score(_els(F, F, F), True, "305-1") == 5


def test_all_missing_is_1():
    assert compute_score(_els(M, M, M), True, "305-1") == 1


def test_all_partial_is_3():
    # f = 0.5 -> band 3
    assert compute_score(_els(P, P), True, "305-1") == 3


def test_three_of_four_found_is_4():
    # f = 0.75 -> band 4 (substantial, minor gap)
    assert compute_score(_els(F, F, F, M), True, "305-1") == 4


def test_one_of_four_found_is_2():
    # f = 0.25 -> band 2 (minimal)
    assert compute_score(_els(F, M, M, M), True, "305-1") == 2


def test_partial_pulls_complete_off_5():
    # all addressed but one only partial: f = (1+1+0.5)/3 = 0.833 -> 4 not 5
    assert compute_score(_els(F, F, P), True, "305-1") == 4


def test_not_applicable_is_0():
    assert compute_score(_els(M, M), False, "305-1") == 0


def test_na_blocked_for_no_omission_disclosures():
    # GRI forbids omitting these; an LLM "not applicable" must NOT yield 0.
    for did in ("2-1", "2-2", "2-3", "2-4", "2-5", "3-1", "3-2"):
        assert did in NO_OMISSION_DISCLOSURES
        # not applicable claimed, but elements all missing -> 1, never 0
        assert compute_score(_els(M, M), False, did) == 1


def test_empty_elements_is_1():
    assert compute_score([], True, "305-1") == 1


def test_empty_elements_backmaps_holistic_status():
    # The judge can return a holistic status with NO per-element verdicts (the
    # schema allows elements=[], and the markdown-fence fallback parse can omit
    # them). Don't collapse a 'covered' disclosure to 1 (Missing) — back-map the
    # status so the displayed grade matches what was stored.
    assert compute_score([], True, "305-1", status="covered") == 5
    assert compute_score([], True, "305-1", status="partial") == 3
    assert compute_score([], True, "305-1", status="missing") == 1


def test_empty_elements_without_status_stays_conservative():
    # No status to fall back on (e.g. legacy callers) -> 1, unchanged.
    assert compute_score([], True, "305-1", status=None) == 1
    assert compute_score([], True, "305-1", status="error") == 1


def test_empty_elements_not_applicable_still_0():
    # NA guard runs before the empty-elements branch: a non-omittable... no, an
    # omittable disclosure judged not-applicable is still 0 regardless of status.
    assert compute_score([], False, "305-1", status="covered") == 0


def test_present_elements_ignore_status():
    # When elements exist they remain authoritative; status is not consulted.
    assert compute_score(_els(M, M, M), True, "305-1", status="covered") == 1


def test_one_third_found_is_band_3():
    # f = 1/3 = 0.333... > cutoff_low (0.33) -> band 3, not 2. Pins the
    # boundary so it can't silently drift when cutoffs become configurable.
    assert compute_score(_els(F, M, M), True, "305-1") == 3


def test_score_from_legacy_status():
    assert score_from_legacy_status("covered") == 5
    assert score_from_legacy_status("partial") == 3
    assert score_from_legacy_status("missing") == 1
    assert score_from_legacy_status("error") is None
    assert score_from_legacy_status("nonsense") is None


def test_effective_score_prefers_explicit_then_backmaps():
    from accordance.judge.rollup import effective_score
    assert effective_score({"score": 4, "status": "covered"}) == 4
    assert effective_score({"score": 0, "status": "missing"}) == 0   # explicit 0 wins
    assert effective_score({"score": None, "status": "covered"}) == 5
    assert effective_score({"score": None, "status": "missing"}) == 1
    assert effective_score({"score": None, "status": "error"}) is None
