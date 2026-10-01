from pathlib import Path

from accordance.extractor.docling_extractor import extract_pdf

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_report.pdf"


def test_extract_pdf_returns_report():
    report = extract_pdf(FIXTURE)
    assert report.source_sha256
    assert len(report.pages) >= 1
    assert all(p.page_number >= 1 for p in report.pages)
    combined = "\n".join(p.markdown for p in report.pages)
    assert len(combined) > 10
