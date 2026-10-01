from accordance.extractor.models import ExtractedPage, ExtractedReport


def test_extracted_report_serializable():
    page = ExtractedPage(page_number=1, markdown="# Heading\n\nSome text", tables=[])
    report = ExtractedReport(source_sha256="abc", pages=[page])
    j = report.model_dump_json()
    assert "Some text" in j


def test_extracted_report_from_pages():
    report = ExtractedReport.model_validate_json(
        '{"source_sha256":"abc","pages":[{"page_number":1,"markdown":"hi","tables":[]}]}'
    )
    assert report.pages[0].markdown == "hi"
