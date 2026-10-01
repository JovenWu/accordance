"""Snap an LLM-produced evidence excerpt to verbatim PDF page text.

The judge often paraphrases its `evidence_excerpt`, reformats numbers, or
reconstructs table cells — and it quotes the *markdown* we feed it, not the
glyph text the PDF viewer renders. Either way the stored quote may not exist
verbatim in the PDF, so the frontend can't highlight it accurately.

This module fixes that deterministically: given the LLM's excerpt and the
actual text of the cited page (PyMuPDF `get_text`, the same glyphs pdf.js
renders), it returns the exact contiguous span of *page* text the excerpt
best corresponds to. The stored excerpt becomes real report text, so the
highlight lands exactly on it. If the excerpt can't be located with
confidence — on the cited page or any other retrieved page — it's dropped
(an honest "no quotable passage" beats a confidently-wrong one).

`best_verbatim_span` / `snap_excerpt` are pure: they take page text (or a
`get_page_text` callable). PDF I/O lives in `make_page_text_provider`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path

# Normalization mirrors the frontend matcher (evidenceMatch.ts) so a span we
# store here is found the same way the text layer is matched in the browser.
_DROP = set('"\'`´“”„‟‘’‚‛′″­​‌‍⁠﻿')
_DASH = set("‐‑‒–—―−⁃")
_LIG = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
_WS = re.compile(r"\s")

# Confidence gates for a fuzzy snap (an exact substring always snaps).
_MIN_EXCERPT_CHARS = 12   # too-short excerpts aren't worth locating
_MIN_BLOCK = 4            # ignore trivially small matching blocks
_LONG_BLOCK = 50          # a verbatim run this long is trustworthy on its own
_MIN_COVERAGE = 0.6       # …or most of the excerpt must be present

# Narrative sentence-expansion: widen a matched span to the enclosing sentence
# so the stored quote reads as a complete supporting sentence instead of a
# mid-sentence fragment. Only for prose (>= _MIN_SENTENCE_WORDS alphabetic
# words); numeric/garbled table cells are left verbatim. Bounded so a missing
# terminator can't run the highlight away.
_MIN_SENTENCE_WORDS = 4
_MAX_SENTENCE_CHARS = 400
_SENT_END = ".!?"
_WORD_RE = re.compile(r"[^\W\d_]{2,}")
_NUM_RE = re.compile(r"\d+")
# Expansion that swallows this many MORE number tokens than the matched span
# is crossing table cells (a flattened multi-metric row), not extending a
# sentence — abandon it.
_MAX_EXTRA_NUMBERS = 2


def _map_char(ch: str) -> str:
    if ch in _DROP:
        return ""
    if _WS.match(ch):
        return " "
    if ch in _LIG:
        return _LIG[ch]
    if ch in _DASH:
        return "-"
    return ch.lower()


def _normalize_with_map(raw: str) -> tuple[str, list[int]]:
    """Normalize `raw`, returning (normalized, map) where map[k] is the index
    in `raw` that normalized char k came from."""
    out: list[str] = []
    idx: list[int] = []
    prev_space = True  # trims leading whitespace
    n = len(raw)
    for i, ch in enumerate(raw):
        if ch == "," and 0 < i < n - 1 and raw[i - 1].isdigit() and raw[i + 1].isdigit():
            continue  # thousands separator inside a number
        mapped = _map_char(ch)
        if mapped == "":
            continue
        if mapped == " ":
            if prev_space:
                continue
            out.append(" ")
            idx.append(i)
            prev_space = True
            continue
        for c in mapped:
            out.append(c)
            idx.append(i)
        prev_space = False
    while out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def _normalize(s: str) -> str:
    return _normalize_with_map(s)[0]


def _raw_offsets(idx: list[int], n_start: int, n_end: int) -> tuple[int, int] | None:
    """Raw-text [start, end) offsets covering normalized range [n_start, n_end),
    or None when the normalized start is past the end of the map."""
    if n_start >= len(idx):
        return None
    raw_start = idx[n_start]
    raw_end = idx[min(n_end, len(idx)) - 1] + 1
    return raw_start, raw_end


def _clean(raw_slice: str) -> str:
    """Collapse whitespace (incl. the PDF's hard line breaks) to single spaces
    so the stored quote reads cleanly; the frontend normalizes the same way, so
    it still matches the text layer exactly."""
    return re.sub(r"\s+", " ", raw_slice).strip()


def _is_boundary(text: str, i: int) -> bool:
    """True when ``text[i]`` is a sentence-ending terminator — i.e. one of
    ``.!?`` that is followed by whitespace/end and is NOT a decimal point
    (preceded by a digit, e.g. the ``.`` in "3.5"). Avoids starting/ending a
    span mid-number.
    """
    if i < 0 or i >= len(text) or text[i] not in _SENT_END:
        return False
    if i > 0 and text[i - 1].isdigit():
        return False
    nxt = text[i + 1] if i + 1 < len(text) else " "
    return nxt.isspace()


def _expand_to_sentence(text: str, start: int, end: int) -> tuple[int, int]:
    """Widen [start, end) to the enclosing sentence for a NARRATIVE span.

    A prose span (>= ``_MIN_SENTENCE_WORDS`` alphabetic words) is grown left to
    just after the previous sentence terminator / line break and right to
    include the next terminator, bounded by ``_MAX_SENTENCE_CHARS`` each way and
    only when a real boundary is found (never an arbitrary cut). Numeric/garbled
    cells (few words) are returned unchanged so credited table figures stay
    verbatim. Expansion is abandoned if it would swallow several more number
    tokens than the matched span (a flattened multi-metric table row, not a
    sentence).
    """
    if len(_WORD_RE.findall(text[start:end])) < _MIN_SENTENCE_WORDS:
        return start, end

    lo = max(0, start - _MAX_SENTENCE_CHARS)
    s = start
    while s > lo and not _is_boundary(text, s - 1) and text[s - 1] != "\n":
        s -= 1
    if s != 0 and not _is_boundary(text, s - 1) and text[s - 1] != "\n":
        s = start  # no boundary within the window — don't cut arbitrarily

    hi = min(len(text), end + _MAX_SENTENCE_CHARS)
    e = end
    found_end = _is_boundary(text, end - 1)
    while e < hi and not found_end:
        if text[e] == "\n":
            break
        e += 1
        if _is_boundary(text, e - 1):
            found_end = True
    if not found_end:
        e = end  # no terminator within the window — keep the original end

    # Crossing several numeric cells means this is a flattened table row, not a
    # sentence — keep the verbatim matched span instead of a number-soup region.
    before = len(_NUM_RE.findall(text[start:end]))
    after = len(_NUM_RE.findall(text[s:e]))
    if after - before >= _MAX_EXTRA_NUMBERS:
        return start, end
    return s, e


def best_verbatim_span(excerpt: str, page_text: str) -> str | None:
    """Return the exact contiguous span of `page_text` that the `excerpt`
    best corresponds to (verbatim report text), or None if no confident match.
    """
    norm_ex = _normalize(excerpt)
    if len(norm_ex) < _MIN_EXCERPT_CHARS:
        return None
    norm_pg, idx = _normalize_with_map(page_text)
    if not norm_pg:
        return None

    # Best case: the excerpt is already verbatim on the page.
    pos = norm_pg.find(norm_ex)
    if pos >= 0:
        off = _raw_offsets(idx, pos, pos + len(norm_ex))
    else:
        # Otherwise align the excerpt against the page and take the matched region.
        sm = SequenceMatcher(None, norm_pg, norm_ex, autojunk=False)
        blocks = [b for b in sm.get_matching_blocks() if b.size >= _MIN_BLOCK]
        if not blocks:
            return None
        matched = sum(b.size for b in blocks)
        coverage = matched / len(norm_ex)
        longest = max(b.size for b in blocks)
        if coverage < _MIN_COVERAGE and longest < _LONG_BLOCK:
            return None  # only coincidental overlap — don't snap to the wrong text

        start = blocks[0].a
        end = blocks[-1].a + blocks[-1].size
        # Scattered matches spanning far more page than the excerpt -> keep the
        # single longest verbatim block instead of a sprawling region.
        if end - start > len(norm_ex) * 2:
            b = max(blocks, key=lambda x: x.size)
            start, end = b.a, b.a + b.size
        off = _raw_offsets(idx, start, end)

    if off is None:
        return None
    raw_start, raw_end = _expand_to_sentence(page_text, *off)
    return _clean(page_text[raw_start:raw_end]) or None


def snap_excerpt(
    excerpt: str | None,
    cited_page: int | None,
    candidate_pages: list[int],
    get_page_text: Callable[[int], str],
) -> tuple[str | None, int | None]:
    """Snap `excerpt` to verbatim text on the cited page, falling back to the
    other retrieved pages (which also corrects a wrong cited page).

    Returns (snapped_text, page) on success, or (None, None) when the excerpt
    can't be confidently located anywhere.
    """
    if not excerpt or not excerpt.strip():
        return None, None

    pages: list[int] = []
    for p in [cited_page, *candidate_pages]:
        if p is not None and p not in pages:
            pages.append(p)

    for p in pages:
        text = get_page_text(p)
        if not text:
            continue
        span = best_verbatim_span(excerpt, text)
        if span:
            return span, p
    return None, None


def make_page_text_provider(pdf_path: Path) -> _PageTextProvider:
    """Open `pdf_path` and return a closeable callable page -> glyph text.

    Caches per-page text. Close it when done (it holds an open PyMuPDF doc).
    """
    return _PageTextProvider(pdf_path)


class _PageTextProvider:
    def __init__(self, pdf_path: Path) -> None:
        self._path = pdf_path
        self._doc = None
        self._failed = False
        self._cache: dict[int, str] = {}

    def __call__(self, page: int) -> str:
        if page in self._cache:
            return self._cache[page]
        if self._doc is None and not self._failed:
            import fitz  # lazy: only pay the import when we actually snap

            try:
                self._doc = fitz.open(str(self._path))
            except Exception:
                self._failed = True  # missing/corrupt PDF -> just no snap
        text = ""
        if self._doc is not None and 1 <= page <= self._doc.page_count:
            try:
                text = self._doc[page - 1].get_text("text")
            except Exception:
                text = ""
        self._cache[page] = text
        return text

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None
