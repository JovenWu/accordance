"""Extractor router.

Dispatches `extract_pdf` to one of the supported backends based on
`Settings.extractor_backend`. Keeps callers ignorant of which backend
is active so swapping is a config-only change.

Backends:
  - "pymupdf"  (default) — fast, low-memory, embedded-text only.
  - "docling" — ML-based, supports OCR + table-cell layout.
"""

from __future__ import annotations

from pathlib import Path

from accordance.config import get_settings
from accordance.extractor.models import ExtractedPage, ExtractedReport

__all__ = ["ExtractedPage", "ExtractedReport", "extract_pdf"]


def extract_pdf(pdf_path: Path) -> ExtractedReport:
    backend = get_settings().extractor_backend.lower()
    if backend == "docling":
        from accordance.extractor.docling_extractor import extract_pdf as _impl
    else:
        from accordance.extractor.pymupdf_extractor import extract_pdf as _impl
    return _impl(pdf_path)
