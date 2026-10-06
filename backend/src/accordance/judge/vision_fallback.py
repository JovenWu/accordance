"""Vision fallback for chart/table-only disclosures.

Some disclosures (305-1 emissions tables, 303 water breakdowns, 2-7
employee tables) routinely return ``needs_vision_fallback: true`` from
the text-pass judge because Docling's markdown for charts is just
"see Figure 4". This module re-judges those disclosures by rendering
the candidate pages as PNG and asking the same LLM to look at the
images directly.

Triggered from ``graph.nodes.judge_one_node`` when ``VISION_FALLBACK_ENABLED``
is set AND either: the text pass returned ``needs_vision_fallback=true``, OR
``VISION_FALLBACK_ON_LOW_CONFIDENCE`` is on and the text verdict was
``partial``/``missing`` (bounded by ``VISION_FALLBACK_BUDGET`` per run). The
low-confidence trigger is the important one in practice — the LLM almost
never self-flags on reports whose data is locked in table-images.

Page rendering uses PyMuPDF (fitz) — pure-Python, no Poppler dep.
"""

from __future__ import annotations

import base64
import functools
import math
from pathlib import Path

import fitz
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from accordance.judge.core import _extract_json
from accordance.judge.output_schema import (
    DisclosureStatus,
    ElementJudgment,
    ElementStatus,
    JudgeOutput,
)
from accordance.judge.prompts import (
    SYSTEM_PROMPT,
    render_elements_list,
    render_hints,
)
from accordance.kb.schema import Disclosure

_ELEMENT_RANK = {
    ElementStatus.found: 0,
    ElementStatus.partial: 1,
    ElementStatus.missing: 2,
}


def merge_verdicts(text_out: JudgeOutput, vision_out: JudgeOutput) -> JudgeOutput:
    """Combine a text-pass verdict with a vision re-judge — vision may only
    UPGRADE, never downgrade.

    The vision pass sees fewer pages than the text pass (rendering every
    retrieved page as an image is too expensive), so a vision "missing" is
    *less* informed than a text "partial" — it usually means the data wasn't
    on the handful of pages we rendered, not that it's absent. Taking the
    best status per element guarantees the vision pass can only help:

    - per element: keep the stronger of (text status, vision status)
    - overall: recompute from merged elements (covered if all found,
      missing if all missing, else partial)
    - evidence: prefer the vision pass's quote when it improved the verdict
      (it transcribed a real table cell); otherwise keep the text quote.
    """
    by_id: dict[str, ElementJudgment] = {e.id: e for e in text_out.elements}
    for ve in vision_out.elements:
        te = by_id.get(ve.id)
        if te is None or _ELEMENT_RANK[ve.status] < _ELEMENT_RANK[te.status]:
            by_id[ve.id] = ve

    merged_elements = list(by_id.values())
    ranks = [_ELEMENT_RANK[e.status] for e in merged_elements]
    if merged_elements and all(r == 0 for r in ranks):
        overall = DisclosureStatus.covered
    elif merged_elements and all(r == 2 for r in ranks):
        overall = DisclosureStatus.missing
    else:
        overall = DisclosureStatus.partial

    text_overall_rank = _status_rank(text_out.status)
    merged_rank = _status_rank(overall)
    vision_helped = merged_rank < text_overall_rank
    if vision_helped and vision_out.evidence_excerpt:
        evidence_excerpt = vision_out.evidence_excerpt
        evidence_page = vision_out.evidence_page
    else:
        evidence_excerpt = text_out.evidence_excerpt
        evidence_page = text_out.evidence_page

    note = vision_out.note if vision_helped else text_out.note

    return JudgeOutput(
        status=overall,
        elements=merged_elements,
        note=note,
        evidence_excerpt=evidence_excerpt,
        evidence_page=evidence_page,
        needs_vision_fallback=False,
        applicable=text_out.applicable,
        na_reason=text_out.na_reason,
    )


def _status_rank(s: DisclosureStatus) -> int:
    return {
        DisclosureStatus.covered: 0,
        DisclosureStatus.partial: 1,
        DisclosureStatus.missing: 2,
        DisclosureStatus.error: 3,
    }[s]


_VISION_USER_TEMPLATE = """\
DISCLOSURE: {disclosure_id} - {disclosure_title}
STANDARD: {standard}

REQUIREMENT:
{requirement_text}

REQUIRED ELEMENTS:
{elements_list}

EVIDENCE HINTS:
{evidence_hints}

The text extraction layer couldn't find this disclosure's data — it may
live in a chart, table, infographic, or other visual element. The
page image(s) below are the candidates retrieval surfaced. Look at the
images directly: check axis labels, table cells, callout numbers, etc.

For evidence_excerpt, transcribe the most relevant cell or label exactly
as it appears in the image (e.g., "Scope 1: 12,450 tCO2e" from a table
row). evidence_page is the page the image was rendered from.

Return JSON matching the schema."""


_MAX_PAGES = 4

_RENDER_ZOOM = 2.0

_MAX_RENDER_PIXELS = 40_000_000


def _clamp_zoom(width_pt: float, height_pt: float, zoom: float) -> float:
    """Reduce ``zoom`` so ``(width*zoom) * (height*zoom)`` stays under
    ``_MAX_RENDER_PIXELS``. Returns ``zoom`` unchanged for normal-sized pages."""
    width = max(1.0, width_pt)
    height = max(1.0, height_pt)
    pixels = (width * zoom) * (height * zoom)
    if pixels <= _MAX_RENDER_PIXELS:
        return zoom
    return zoom * math.sqrt(_MAX_RENDER_PIXELS / pixels)


@functools.lru_cache(maxsize=64)
def _render_page_png(pdf_path: Path, page_number: int, zoom: float = _RENDER_ZOOM) -> bytes:
    """Render a single page to PNG bytes. page_number is 1-indexed.

    Results are cached in-process by (pdf_path, page_number, zoom) so the
    same page is not re-rasterised when multiple disclosures reference it.
    Cache is bounded (maxsize=64) to cap memory use.

    The effective zoom is clamped so an oversized (or maliciously huge) page
    can't blow up into a multi-GB pixmap — see ``_MAX_RENDER_PIXELS``.

    Raises if the page is out of range or the PDF can't be opened.
    """
    doc = fitz.open(str(pdf_path))
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise IndexError(
                f"page {page_number} out of range (PDF has {doc.page_count} pages)"
            )
        page = doc[page_number - 1]
        safe_zoom = _clamp_zoom(page.rect.width, page.rect.height, zoom)
        pix = page.get_pixmap(matrix=fitz.Matrix(safe_zoom, safe_zoom))
        return pix.tobytes("png")
    finally:
        doc.close()


def _build_vision_messages(
    disclosure: Disclosure,
    rendered: list[tuple[int, bytes]],
):
    """Construct the multimodal message list for the vision judge call."""
    user_text = _VISION_USER_TEMPLATE.format(
        disclosure_id=disclosure.id,
        disclosure_title=disclosure.title,
        standard=disclosure.standard,
        requirement_text=disclosure.requirement_text,
        elements_list=render_elements_list(disclosure.required_elements),
        evidence_hints=render_hints(disclosure.good_evidence_hints),
    )

    content: list[dict] = [{"type": "text", "text": user_text}]
    for page_num, png in rendered:
        b64 = base64.b64encode(png).decode("ascii")
        content.append({"type": "text", "text": f"--- page {page_num} image ---"})
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            }
        )

    return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=content)]


def judge_with_vision(
    disclosure: Disclosure,
    pdf_path: Path,
    pages: list[int],
    llm: BaseChatModel,
) -> JudgeOutput:
    """Re-judge a disclosure using rendered page images.

    `pages` are the candidate pages the retrieval surfaced (typically the
    distinct pages from the top-3 dense hits). Capped to _MAX_PAGES.

    Raises ``RuntimeError`` if no pages could be rendered — caller
    (graph.nodes.judge_one_node) catches this and falls back to the
    original text verdict.
    """
    candidate_pages = pages[:_MAX_PAGES] if pages else [1]

    rendered: list[tuple[int, bytes]] = []
    last_render_err: Exception | None = None
    for p in candidate_pages:
        try:
            rendered.append((p, _render_page_png(pdf_path, p)))
        except Exception as e:
            last_render_err = e

    if not rendered:
        raise RuntimeError(
            f"Could not render any pages {candidate_pages} from {pdf_path}: "
            f"{last_render_err}"
        )

    messages = _build_vision_messages(disclosure, rendered)

    try:
        structured = llm.with_structured_output(JudgeOutput)
        return structured.invoke(messages)
    except Exception:
        resp = llm.invoke(messages)
        text = resp.content if hasattr(resp, "content") else str(resp)
        if isinstance(text, list):
            text = "".join(
                (c.get("text", "") if isinstance(c, dict) else str(c)) for c in text
            )
        return JudgeOutput.model_validate_json(_extract_json(text))
