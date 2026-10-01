from datetime import datetime, timezone

import fitz  # PyMuPDF

from accordance.exporters.analysis_report import (
    AnalysisReport,
    StandardSummary,
    analysis_report_bytes,
)


def _data() -> AnalysisReport:
    return AnalysisReport(
        report_name="Acme Sustainability Report 2024",
        version=2,
        pdf_filename="acme-2024.pdf",
        run_id="61945a29-67fd-45c3-b99a-d7c1f05f1413",
        pdf_sha256="a" * 64,
        completed_at=datetime(2024, 6, 1, 12, 30, tzinfo=timezone.utc),
        page_count=298,
        dist={5: 10, 4: 13, 3: 9, 2: 1, 1: 0, 0: 0},
        errors=0,
        coverage=0.78,
        avg=3.9,
        standards=[
            StandardSummary(
                name="GRI 2: General Disclosures 2021",
                assessed=30, scored=30, avg=3.9, coverage=0.78,
            ),
            StandardSummary(
                name="GRI 305: Emissions 2016",
                assessed=3, scored=3, avg=4.0, coverage=0.80,
            ),
        ],
    )


def test_analysis_report_is_a_single_page_pdf_with_key_content():
    blob = analysis_report_bytes(_data())
    assert blob.startswith(b"%PDF")
    doc = fitz.open(stream=blob, filetype="pdf")
    assert doc.page_count == 1
    text = doc[0].get_text()
    for needle in [
        "ACCORDANCE",
        "ANALYSIS REPORT",
        "Acme Sustainability Report 2024",
        "v2",
        "acme-2024.pdf",
        "78%",                      # coverage score
        "33",                       # disclosures assessed
        "3.9 / 5",                  # average grade
        "298",                      # pages analysed
        "Grade distribution",
        "Complete",                 # legend label
        "Coverage by standard",
        "GRI 2: General Disclosures 2021",
        "VERIFICATION",
        "61945a29-67fd-45c3-b99a-d7c1f05f1413",
        "a" * 64,
        "not an assurance opinion",
    ]:
        assert needle in text, needle


def test_analysis_report_handles_empty_and_missing_values():
    data = _data()
    data.dist = {s: 0 for s in range(6)}
    data.coverage = None
    data.avg = None
    data.completed_at = None
    data.page_count = 0
    data.standards = []
    blob = analysis_report_bytes(data)
    doc = fitz.open(stream=blob, filetype="pdf")
    text = doc[0].get_text()
    assert "-" in text  # placeholder rendered for missing metrics


def test_analysis_report_caps_long_standard_tables():
    data = _data()
    data.standards = [
        StandardSummary(name=f"GRI {i}: Std", assessed=1, scored=1, avg=1.0, coverage=0.2)
        for i in range(30)
    ]
    text = fitz.open(stream=analysis_report_bytes(data), filetype="pdf")[0].get_text()
    assert "more standards" in text
    assert doc_page_count(analysis_report_bytes(data)) == 1


def doc_page_count(blob) -> int:
    return fitz.open(stream=blob, filetype="pdf").page_count
