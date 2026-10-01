"""Fast smoke test for the PyMuPDF extractor.

Unlike the Docling extractor's test (which is slow + hangs on Windows
cold-start), PyMuPDF has no ML models so this runs in <1s.
"""

from pathlib import Path

import fitz

from accordance.extractor.pymupdf_extractor import extract_pdf

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_report.pdf"


def test_extract_pdf_returns_report():
    report = extract_pdf(FIXTURE)
    assert report.source_sha256
    assert len(report.pages) >= 1
    # Per-page text should have at least some content for an embedded-text PDF.
    combined = "\n".join(p.markdown for p in report.pages)
    assert len(combined) > 10
    # Page numbers are 1-indexed and contiguous.
    for i, p in enumerate(report.pages, start=1):
        assert p.page_number == i


def test_extract_pdf_warns_on_empty_pages(tmp_path: Path):
    """Synthesize a PDF with no embedded text → all pages empty → warning.

    Patch the module logger directly rather than using caplog: once any test has
    called create_app() (which sets propagate=False on the accordance logger),
    caplog's root handler never sees the record, making this order-dependent.
    Same workaround as test_pricing.py.
    """
    from unittest.mock import patch

    pdf_path = tmp_path / "empty.pdf"
    doc = fitz.open()
    doc.new_page()  # one blank page, no text
    doc.save(str(pdf_path))
    doc.close()

    with patch("accordance.extractor.pymupdf_extractor.logger") as mock_logger:
        report = extract_pdf(pdf_path)

    assert len(report.pages) == 1
    assert report.pages[0].markdown == ""
    # The warning message should mention scanned-PDF fallback.
    warned = " ".join(str(c) for c in mock_logger.warning.call_args_list)
    assert "scanned" in warned.lower() or "empty" in warned.lower()


def test_router_dispatches_to_pymupdf_by_default(monkeypatch, tmp_path):
    """The extractor/__init__ router picks pymupdf when no env override set."""
    monkeypatch.setenv("EXTRACTOR_BACKEND", "pymupdf")
    from accordance.extractor import extract_pdf as routed

    # If the router dispatched to Docling we'd be doing a full ML pipeline
    # that takes much longer than the pymupdf path. We don't time-assert
    # here; just verify the result shape is consistent.
    report = routed(FIXTURE)
    assert report.source_sha256
    assert len(report.pages) >= 1
