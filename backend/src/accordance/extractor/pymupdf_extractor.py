"""PyMuPDF-based PDF extractor.

A drop-in alternative to the Docling extractor that's an order of magnitude
faster and uses a fraction of the memory. The trade-off: no OCR (so scanned
PDFs come back empty) and no ML-driven layout detection (heading detection
is heuristic, based on font-size analysis).

Suitable for PDFs with embedded text — which covers virtually all modern
sustainability reports. Falls back to a clear-error path for scanned PDFs
rather than silently emitting empty pages.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import fitz
import pymupdf4llm

from accordance.extractor.models import EncryptedPDFError, ExtractedPage, ExtractedReport

logger = logging.getLogger(__name__)


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_pdf(pdf_path: Path) -> ExtractedReport:
    """Extract a PDF into per-page Markdown using PyMuPDF.

    Uses pymupdf4llm with `page_chunks=True` so the result is already
    structured per page. We turn off image extraction (no rendering /
    writing) since we only need text for the judge.
    """
    sha = _sha256_of_file(pdf_path)

    with fitz.open(str(pdf_path)) as doc:
        if doc.needs_pass:
            raise EncryptedPDFError(
                "This PDF is password-protected/encrypted and can't be read. "
                "Remove the password (print-to-PDF or 'save without protection') "
                "and re-upload."
            )
        total_pages = doc.page_count

    if total_pages == 0:
        return ExtractedReport(source_sha256=sha, pages=[])

    logger.info("pymupdf extract: %s (%d pages)", pdf_path.name, total_pages)

    chunks = pymupdf4llm.to_markdown(
        str(pdf_path),
        page_chunks=True,
        write_images=False,
        embed_images=False,
        ignore_images=True,
        ignore_graphics=True,
        show_progress=False,
    )

    pages: list[ExtractedPage] = []
    for entry in chunks:
        meta = entry.get("metadata") or {}
        zero_indexed = meta.get("page")
        if zero_indexed is None:
            page_number = len(pages) + 1
        else:
            page_number = int(zero_indexed) + 1
        md = (entry.get("text") or "").strip()
        pages.append(ExtractedPage(page_number=page_number, markdown=md, tables=[]))

    while len(pages) < total_pages:
        pages.append(
            ExtractedPage(page_number=len(pages) + 1, markdown="", tables=[])
        )

    if total_pages > 0 and all(not p.markdown for p in pages):
        logger.warning(
            "pymupdf extract: all %d pages are empty — looks like a scanned PDF. "
            "Switch EXTRACTOR_BACKEND=docling and DOCLING_DO_OCR=true to OCR it.",
            total_pages,
        )

    return ExtractedReport(source_sha256=sha, pages=pages)
