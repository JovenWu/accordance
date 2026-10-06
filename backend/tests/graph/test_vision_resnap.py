"""Vision-fallback evidence must pass through the same snap gate as the text
path (diagnosis RC2): the merge installs the vision model's raw image
transcription verbatim, which may not exist in the page text layer and would
highlight as gibberish. snap_evidence_in_place re-anchors or drops it.
"""

from accordance.graph.nodes import snap_evidence_in_place
from accordance.judge.output_schema import (
    DisclosureStatus,
    ElementJudgment,
    ElementStatus,
    JudgeOutput,
)


def _out(excerpt, page):
    return JudgeOutput(
        status=DisclosureStatus.covered,
        elements=[ElementJudgment(id="a", status=ElementStatus.found, page=page)],
        note="n",
        evidence_excerpt=excerpt,
        evidence_page=page,
        needs_vision_fallback=False,
        applicable=True,
        na_reason=None,
    )


def test_drops_vision_excerpt_absent_from_text_layer():
    page = "Greenhouse gas emissions are shown in the chart on this page."
    out = _out("Scope 1: 12,450 tCO2e", 9)
    snap_evidence_in_place(out, [9], lambda p: {9: page}.get(p, ""))
    assert out.evidence_excerpt is None
    assert out.evidence_page is None
    assert out.status == DisclosureStatus.covered


def test_keeps_and_snaps_a_locatable_excerpt():
    page = (
        "Our Scope 1 emissions for FY2024 totaled 12,450 tCO2e from stationary "
        "and mobile combustion."
    )
    out = _out("Scope 1 emissions for FY2024 totaled 12,450 tCO2e", 9)
    snap_evidence_in_place(out, [9], lambda p: {9: page}.get(p, ""))
    assert out.evidence_excerpt is not None
    assert "12,450 tCO2e" in out.evidence_excerpt
    assert out.evidence_page == 9


def test_noop_when_no_excerpt():
    out = _out(None, None)
    snap_evidence_in_place(out, [1], lambda p: "anything")
    assert out.evidence_excerpt is None
