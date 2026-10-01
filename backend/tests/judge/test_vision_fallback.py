"""Tests for the vision fallback re-judge path."""

import base64
from pathlib import Path

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from accordance.judge.output_schema import (
    DisclosureStatus,
    ElementJudgment,
    ElementStatus,
    JudgeOutput,
)
from accordance.judge.vision_fallback import (
    _MAX_RENDER_PIXELS,
    _RENDER_ZOOM,
    _build_vision_messages,
    _clamp_zoom,
    _render_page_png,
    judge_with_vision,
    merge_verdicts,
)
from accordance.kb.schema import Disclosure, RequiredElement

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_report.pdf"


def _el(id_, status, page=None):
    return ElementJudgment(id=id_, status=ElementStatus(status), page=page)


def test_clamp_zoom_leaves_normal_pages_unchanged():
    # A4 (595x842 pt) at zoom 2.0 is ~2 MP — well under the cap, unchanged.
    assert _clamp_zoom(595, 842, _RENDER_ZOOM) == _RENDER_ZOOM
    # US Letter, A3 — all comfortably below the cap.
    assert _clamp_zoom(612, 792, _RENDER_ZOOM) == _RENDER_ZOOM
    assert _clamp_zoom(842, 1191, _RENDER_ZOOM) == _RENDER_ZOOM


def test_clamp_zoom_bounds_a_pixel_bomb_page():
    # A spec-max 14400x14400 pt page at zoom 2.0 would be ~830 MP (a multi-GB
    # pixmap). The clamp must reduce zoom so the output stays under the cap.
    z = _clamp_zoom(14400, 14400, _RENDER_ZOOM)
    assert z < _RENDER_ZOOM
    pixels = (14400 * z) * (14400 * z)
    assert pixels <= _MAX_RENDER_PIXELS * 1.0001  # within float tolerance


def test_clamp_zoom_handles_degenerate_zero_size():
    # A zero/negative MediaBox must not divide-by-zero; treated as 1pt minimum.
    assert _clamp_zoom(0, 0, _RENDER_ZOOM) == _RENDER_ZOOM


def test_merge_never_downgrades_a_text_finding():
    """Vision seeing too few pages and finding nothing must NOT regress the
    text pass's partial verdict — the bug that turned 4 partials into missing
    on the VALE run."""
    text = JudgeOutput(
        status=DisclosureStatus.partial,
        elements=[_el("a", "found", 5), _el("b", "missing")],
        note="text found a",
        evidence_excerpt="text quote",
        evidence_page=5,
    )
    vision = JudgeOutput(
        status=DisclosureStatus.missing,
        elements=[_el("a", "missing"), _el("b", "missing")],
        note="vision saw nothing",
        evidence_excerpt=None,
        evidence_page=None,
    )
    merged = merge_verdicts(text, vision)
    assert merged.status == DisclosureStatus.partial  # NOT missing
    statuses = {e.id: e.status for e in merged.elements}
    assert statuses["a"] == ElementStatus.found  # text's find preserved
    assert statuses["b"] == ElementStatus.missing
    assert merged.evidence_excerpt == "text quote"


def test_merge_upgrades_when_vision_finds_more():
    text = JudgeOutput(
        status=DisclosureStatus.missing,
        elements=[_el("a", "missing"), _el("b", "missing")],
        note="text found nothing",
        evidence_excerpt=None,
        evidence_page=None,
    )
    vision = JudgeOutput(
        status=DisclosureStatus.covered,
        elements=[_el("a", "found", 9), _el("b", "found", 9)],
        note="vision read the table",
        evidence_excerpt="Surface water 41 ML",
        evidence_page=9,
    )
    merged = merge_verdicts(text, vision)
    assert merged.status == DisclosureStatus.covered
    assert merged.evidence_excerpt == "Surface water 41 ML"
    assert merged.evidence_page == 9


def test_merge_mixed_each_side_contributes():
    text = JudgeOutput(
        status=DisclosureStatus.partial,
        elements=[_el("a", "found", 5), _el("b", "missing")],
        note="t", evidence_excerpt="t", evidence_page=5,
    )
    vision = JudgeOutput(
        status=DisclosureStatus.partial,
        elements=[_el("a", "missing"), _el("b", "found", 9)],
        note="v", evidence_excerpt="v", evidence_page=9,
    )
    merged = merge_verdicts(text, vision)
    assert merged.status == DisclosureStatus.covered
    statuses = {e.id: e.status for e in merged.elements}
    assert statuses["a"] == ElementStatus.found
    assert statuses["b"] == ElementStatus.found


class _SpyLLM(BaseChatModel):
    """Captures the last messages it was invoked with, returns canned JSON."""

    def __init__(self, content: str | None = None):
        super().__init__()
        object.__setattr__(self, "_content", content or (
            '{"status":"covered","elements":[{"id":"x","status":"found","page":1}],'
            '"note":"vision found it","evidence_excerpt":"12,450 tCO2e",'
            '"evidence_page":1,"needs_vision_fallback":false}'
        ))
        object.__setattr__(self, "last_messages", None)

    @property
    def _llm_type(self) -> str:
        return "spy"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.outputs import ChatGeneration, ChatResult

        object.__setattr__(self, "last_messages", list(messages))
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self._content))]
        )

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _disclosure() -> Disclosure:
    return Disclosure(
        id="305-1",
        standard="GRI 305",
        title="Scope 1 emissions",
        category="topic",
        requirement_text="Report Scope 1 GHG emissions.",
        required_elements=[
            RequiredElement(id="scope_1", desc="Scope 1 emissions tCO2e"),
        ],
        retrieval_queries=["scope 1 emissions"],
        suggested_fix_template="add an emissions table.",
    )


# ----------------------------------------------------------------------
# _render_page_png
# ----------------------------------------------------------------------


def test_render_page_returns_png_bytes():
    png = _render_page_png(FIXTURE, page_number=1)
    assert isinstance(png, bytes)
    # PNG signature
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    # Non-trivial size — even a single-line PDF should render to >1KB at 2x
    assert len(png) > 1024


def test_render_page_out_of_range_raises():
    with pytest.raises(IndexError):
        _render_page_png(FIXTURE, page_number=999)


def test_render_page_zero_raises():
    """page_number is 1-indexed; 0 should be rejected."""
    with pytest.raises(IndexError):
        _render_page_png(FIXTURE, page_number=0)


# ----------------------------------------------------------------------
# _build_vision_messages
# ----------------------------------------------------------------------


def test_message_structure_has_text_and_images():
    rendered = [(1, b"\x89PNG\r\n\x1a\n_fake_png_bytes_1"),
                (2, b"\x89PNG\r\n\x1a\n_fake_png_bytes_2")]
    messages = _build_vision_messages(_disclosure(), rendered)

    # System + Human only — no AI message
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)

    # System prompt is the same one the text pass uses (preserves few-shot)
    assert "EXAMPLE 1" in messages[0].content

    # Human content is a list of typed blocks
    content = messages[1].content
    assert isinstance(content, list)

    text_blocks = [c for c in content if c["type"] == "text"]
    image_blocks = [c for c in content if c["type"] == "image_url"]

    # 1 main text prompt + 1 label per image
    assert len(text_blocks) == 1 + len(rendered)
    assert len(image_blocks) == len(rendered)

    # Disclosure context surfaced in the main text block
    main_text = text_blocks[0]["text"]
    assert "305-1" in main_text
    assert "Scope 1 emissions" in main_text

    # Images encoded as data URLs with base64 payload
    for blk in image_blocks:
        url = blk["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")


def test_message_includes_page_labels():
    rendered = [(47, b"\x89PNGfake"), (48, b"\x89PNGfake2")]
    messages = _build_vision_messages(_disclosure(), rendered)
    text_blocks = [c for c in messages[1].content if c["type"] == "text"]
    page_labels = [t["text"] for t in text_blocks if "page" in t["text"] and "image" in t["text"]]
    assert any("page 47" in lbl for lbl in page_labels)
    assert any("page 48" in lbl for lbl in page_labels)


def test_image_base64_round_trip():
    """The PNG bytes we passed in should be recoverable from the data URL."""
    png = b"\x89PNG\r\n\x1a\n_exact_bytes_here"
    rendered = [(1, png)]
    messages = _build_vision_messages(_disclosure(), rendered)
    image_block = next(c for c in messages[1].content if c["type"] == "image_url")
    url = image_block["image_url"]["url"]
    b64 = url.removeprefix("data:image/png;base64,")
    assert base64.b64decode(b64) == png


# ----------------------------------------------------------------------
# judge_with_vision (end-to-end with fake LLM)
# ----------------------------------------------------------------------


def test_judge_with_vision_returns_parsed_output():
    llm = _SpyLLM()
    out = judge_with_vision(_disclosure(), FIXTURE, pages=[1], llm=llm)
    assert isinstance(out, JudgeOutput)
    assert out.status.value == "covered"
    assert out.note == "vision found it"
    # The spy captured the multimodal message
    assert llm.last_messages is not None
    assert len(llm.last_messages) == 2


def test_judge_with_vision_caps_page_count():
    llm = _SpyLLM()
    judge_with_vision(_disclosure(), FIXTURE, pages=[1, 1, 1, 1, 1, 1], llm=llm)
    # Capped at _MAX_PAGES (4) even if 6 pages were requested.
    image_blocks = [
        c for c in llm.last_messages[1].content if c["type"] == "image_url"
    ]
    assert len(image_blocks) == 4


def test_judge_with_vision_skips_unrenderable_pages(tmp_path):
    """Bad page numbers are skipped, valid ones still render."""
    llm = _SpyLLM()
    out = judge_with_vision(_disclosure(), FIXTURE, pages=[999, 1, 998], llm=llm)
    assert isinstance(out, JudgeOutput)
    image_blocks = [
        c for c in llm.last_messages[1].content if c["type"] == "image_url"
    ]
    # Only page 1 was valid → exactly 1 image
    assert len(image_blocks) == 1


def test_judge_with_vision_raises_when_no_pages_render(monkeypatch):
    """If every candidate page is invalid, surface a clear error so the
    node falls back to the text verdict."""
    llm = _SpyLLM()
    with pytest.raises(RuntimeError, match="Could not render"):
        judge_with_vision(_disclosure(), FIXTURE, pages=[999, 1000], llm=llm)


def test_judge_with_vision_falls_back_to_markdown_parse():
    """When with_structured_output fails (some proxies wrap output), the
    code path falls back to manual JSON extraction. We re-use the same
    _extract_json helper as the text pass."""
    canned = (
        "```json\n"
        '{"status":"missing","elements":[],"note":"could not see",'
        '"evidence_excerpt":null,"evidence_page":null,"needs_vision_fallback":false}\n'
        "```"
    )

    class _FenceLLM(_SpyLLM):
        def __init__(self):
            super().__init__(content=canned)

        def with_structured_output(self, *_a, **_kw):
            raise RuntimeError("structured output not supported")

    llm = _FenceLLM()
    out = judge_with_vision(_disclosure(), FIXTURE, pages=[1], llm=llm)
    assert out.status.value == "missing"
    assert out.note == "could not see"


# ----------------------------------------------------------------------
# _render_page_png cache — Change 2
# ----------------------------------------------------------------------


def test_render_page_png_returns_identical_bytes_on_repeat_call():
    """Two calls with the same (pdf_path, page, zoom) must return identical bytes."""
    bytes1 = _render_page_png(FIXTURE, page_number=1)
    bytes2 = _render_page_png(FIXTURE, page_number=1)
    assert bytes1 == bytes2


def test_render_page_png_only_rasterizes_once_per_page(monkeypatch):
    """The underlying PyMuPDF rasterisation must be invoked ONCE even when
    _render_page_png is called twice with the same arguments — the second call
    must be served from cache without reopening the PDF.
    """
    import fitz

    from accordance.judge import vision_fallback as vf

    rasterize_calls: list[tuple] = []
    original_get_pixmap = fitz.Page.get_pixmap

    def spy_get_pixmap(self, *args, **kwargs):
        rasterize_calls.append((args, kwargs))
        return original_get_pixmap(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "get_pixmap", spy_get_pixmap)

    # Clear the cache so we start fresh.
    if hasattr(vf._render_page_png, "cache_clear"):
        vf._render_page_png.cache_clear()

    vf._render_page_png(FIXTURE, page_number=1)
    vf._render_page_png(FIXTURE, page_number=1)  # should be cache hit

    assert len(rasterize_calls) == 1, (
        f"Expected 1 rasterise call, got {len(rasterize_calls)} — "
        "cache is not working"
    )
