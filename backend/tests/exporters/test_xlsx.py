import io

from openpyxl import load_workbook

from accordance.exporters.coverage_matrix import MatrixColumn, build_coverage_matrix
from accordance.exporters.xlsx_exporter import to_xlsx_bytes
from accordance.kb.schema import Disclosure


def _disc(disc_id, standard, title):
    return Disclosure(
        id=disc_id, standard=standard, title=title, category="topic",
        requirement_text="x", required_elements=[{"id": "e", "desc": "d"}],
        retrieval_queries=["q"], suggested_fix_template="fix",
    )


def _matrix():
    kb = {
        "2-2": _disc("2-2", "GRI 2: General Disclosures 2021", "Entities"),
        "305-3": _disc("305-3", "GRI 305: Emissions 2016", "Other indirect"),
        "303-3": _disc("303-3", "GRI 303: Water 2018", "Water withdrawal"),
    }
    # 2-2 graded 5; 305-3 N/A (0); 303-3 errored (None -> blank).
    col = MatrixColumn(label="Acme", score_by_id={"2-2": 5, "305-3": 0, "303-3": None})
    return build_coverage_matrix(kb, [col])


def test_xlsx_has_header_and_score_cells():
    ws = load_workbook(io.BytesIO(to_xlsx_bytes(_matrix()))).active
    assert ws.title == "GRI Coverage"
    assert [c.value for c in ws[1]] == ["Standard", "KODE", "INDIKATOR", "Acme"]
    assert ws["A1"].font.bold is True
    by_code = {ws.cell(r, 2).value: ws.cell(r, 4).value for r in range(2, ws.max_row + 1)}
    assert by_code["GRI 2-2"] == 5         # graded 1-5 -> integer
    assert by_code["GRI 305-3"] == "N/A"   # 0 -> "N/A" text
    assert by_code["GRI 303-3"] is None    # error -> blank


def test_xlsx_footer_has_live_formulas():
    ws = load_workbook(io.BytesIO(to_xlsx_bytes(_matrix()))).active
    labels = {ws.cell(r, 3).value: r for r in range(2, ws.max_row + 1)}
    assert "Total score" in labels
    assert "Disclosures checked" in labels
    assert "Coverage score" in labels
    tot, chk, cov = labels["Total score"], labels["Disclosures checked"], labels["Coverage score"]
    # Data rows span 2..(tot-1); footer carries formulas, not precomputed values.
    assert ws.cell(tot, 4).value == f"=SUM(D2:D{tot - 1})"
    assert ws.cell(chk, 4).value == f"=COUNT(D2:D{tot - 1})"
    assert ws.cell(cov, 4).value == f'=IF(D{chk}=0,"",D{tot}/(D{chk}*5))'
    assert ws.cell(cov, 4).number_format == "0.0%"
    assert ws.cell(tot, 4).font.bold is True


def test_xlsx_score_cells_integer_format_and_autofilter():
    ws = load_workbook(io.BytesIO(to_xlsx_bytes(_matrix()))).active
    graded_row = next(
        r for r in range(2, ws.max_row + 1) if ws.cell(r, 2).value == "GRI 2-2"
    )
    assert ws.cell(graded_row, 4).number_format == "0"  # integer 0-5, not 0.0
    assert ws.column_dimensions["C"].width == 50
    # Autofilter spans header + data rows only — the three footer rows are excluded.
    assert ws.auto_filter.ref == f"A1:D{ws.max_row - 3}"
