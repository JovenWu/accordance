import re
from dataclasses import dataclass

import tiktoken

from accordance.extractor.models import ExtractedReport

_ENC = tiktoken.get_encoding("cl100k_base")

# Matches markdown ATX-style headings: 1-6 leading hashes, then text.
# Setext headings (===, ---) are uncommon in Docling output and ignored here.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# A markdown table row: a line that contains pipe cell delimiters, e.g.
# "| a | b |" or a separator "|---|---|".
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")

# OpenAI text-embedding-3-small accepts ~8191 tokens per input. Keep atomic
# table chunks below that so a huge data table can't truncate/err at embed time.
_EMBEDDING_TOKEN_LIMIT = 8_000

# A GRI-style disclosure id, e.g. "2-1", "305-1", "418-1". Year ranges
# ("2024-2025") and similar 4-digit tokens don't match (\d{1,3} caps at 3).
_DISCLOSURE_ID_RE = re.compile(r"\b\d{1,3}-\d{1,3}\b")

# A GRI content index / cross-reference table is a NAVIGATION table mapping
# disclosure ids to page numbers. It is id-dense, so it gets retrieved for
# almost every disclosure query and the judge may cite it instead of the real
# reported content. We detect and drop it at chunk time so it never becomes
# evidence.
#
# Detection requires BOTH a navigation HEADING (e.g. "GRI Content Index",
# "GRI Standards Index", "Table of Contents") AND id-density. The heading is
# the high-precision gate: it is what separates a navigation table from
# id-dense SUBSTANTIVE content — an inline-answered "General Disclosures" page,
# a disclosure-keyed ESG data-summary table, or a material-topics → standard
# mapping table all carry many disclosure ids but are NOT under an index
# heading, so they are kept. The trade-off is recall: a content index with no
# recoverable heading (rare; extraction usually keeps it) is not caught — an
# acceptable miss, since dropping real reported content would silently corrupt
# the grade, which is far worse than occasionally retrieving the index.
_INDEX_HEADING_RE = re.compile(
    r"\b(gri[\w ]{0,20}index|content index|table of contents)\b", re.IGNORECASE
)
_INDEX_MIN_IDS = 8           # distinct disclosure ids on the page/section
_INDEX_MIN_ID_LINE_FRAC = 0.5  # …and most non-blank lines are id rows


def _is_table_line(line: str) -> bool:
    return bool(_TABLE_ROW_RE.match(line))


def _is_content_index(text: str) -> bool:
    """True when `text` looks like a GRI content index / TOC / cross-reference
    navigation table rather than substantive report content.

    All must hold: (1) a content-index / table-of-contents HEADING is present;
    (2) at least `_INDEX_MIN_IDS` DISTINCT disclosure ids appear; (3) at least
    `_INDEX_MIN_ID_LINE_FRAC` of non-blank lines each contain a disclosure id.
    The heading requirement keeps id-dense SUBSTANTIVE content (inline-answered
    disclosures, data-summary tables with a GRI column, topic→standard maps)
    from being dropped.
    """
    if not _INDEX_HEADING_RE.search(text):
        return False
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    if len(set(_DISCLOSURE_ID_RE.findall(text))) < _INDEX_MIN_IDS:
        return False
    id_lines = sum(1 for ln in lines if _DISCLOSURE_ID_RE.search(ln))
    return id_lines / len(lines) >= _INDEX_MIN_ID_LINE_FRAC


def _is_mostly_table(text: str) -> bool:
    """True when >=50% of non-blank lines look like markdown table rows."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    table_lines = sum(1 for ln in lines if _is_table_line(ln))
    return table_lines / len(lines) >= 0.5


@dataclass
class Chunk:
    page: int
    text: str


@dataclass
class _Section:
    heading: str  # full heading line including hashes, or "" for prefix content
    text: str  # heading + body until next same-or-higher-level heading


def _count_tokens(text: str) -> int:
    return len(_ENC.encode(text))


def _split_tokens(text: str, target: int, overlap: int) -> list[str]:
    tokens = _ENC.encode(text)
    if len(tokens) <= target:
        return [text]
    out: list[str] = []
    step = target - overlap
    for start in range(0, len(tokens), step):
        window = tokens[start : start + target]
        out.append(_ENC.decode(window))
        if start + target >= len(tokens):
            break
    return out


def _split_by_headings(md: str) -> list[_Section]:
    """Break a page's markdown into sections at heading boundaries.

    A "section" starts at a heading line and runs until the next heading
    line (or end of input). Content before the first heading becomes a
    leading section with heading="". A page with no headings yields a
    single section with the entire markdown as body.
    """
    matches = list(_HEADING_RE.finditer(md))
    if not matches:
        return [_Section(heading="", text=md)]

    sections: list[_Section] = []
    # Any prose that precedes the first heading is its own section.
    if matches[0].start() > 0:
        prefix = md[: matches[0].start()].rstrip()
        if prefix.strip():
            sections.append(_Section(heading="", text=prefix))

    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        body = md[m.start() : end].rstrip()
        if body.strip():
            sections.append(_Section(heading=m.group(0), text=body))
    return sections


def chunk_report(
    report: ExtractedReport,
    target_tokens: int = 500,
    overlap_tokens: int = 50,
) -> list[Chunk]:
    """Chunk per page, respecting markdown heading boundaries.

    Strategy:
      1. For each page, split its markdown at heading boundaries (#…######).
      2. Sections that fit within `target_tokens` become a single chunk —
         this keeps short tables and short sections together, which the
         token-window splitter would otherwise fragment.
      3. Oversized sections fall back to token-window split, with the
         heading line prepended to every sub-chunk so each piece carries
         its section context (helps retrieval when the relevant info is
         on a later token-window of a long section).

    Chunks never straddle page boundaries.
    """
    chunks: list[Chunk] = []
    for page in report.pages:
        if not page.markdown.strip():
            continue
        # Drop a whole page that is a GRI content index / cross-reference table
        # (caught here even when per-standard sub-headings would fragment it
        # below the per-section id threshold). Navigation, not evidence.
        if _is_content_index(page.markdown):
            continue
        for section in _split_by_headings(page.markdown):
            # …and drop an index/cross-reference table embedded in a mixed page.
            if _is_content_index(section.text):
                continue
            n_tokens = _count_tokens(section.text)
            if n_tokens <= target_tokens:
                chunks.append(Chunk(page=page.page_number, text=section.text))
                continue

            # Keep a table-dominated section whole — token-window splitting a
            # table destroys row/column alignment the judge needs — UNLESS it's
            # too large to embed as one chunk, in which case fall through to split.
            if _is_mostly_table(section.text) and n_tokens <= _EMBEDDING_TOKEN_LIMIT:
                chunks.append(Chunk(page=page.page_number, text=section.text))
                continue

            pieces = _split_tokens(section.text, target_tokens, overlap_tokens)
            if not section.heading:
                for p in pieces:
                    chunks.append(Chunk(page=page.page_number, text=p))
                continue

            # Heading is already embedded in pieces[0]; prepend it to the
            # rest so every sub-chunk has the section context.
            chunks.append(Chunk(page=page.page_number, text=pieces[0]))
            for p in pieces[1:]:
                chunks.append(
                    Chunk(
                        page=page.page_number,
                        text=f"{section.heading}\n\n{p}",
                    )
                )
    return chunks
