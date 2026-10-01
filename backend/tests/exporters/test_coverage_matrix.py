from accordance.exporters.coverage_matrix import (
    MatrixColumn,
    build_coverage_matrix,
)
from accordance.kb.schema import Disclosure


def _disc(disc_id: str, standard: str, title: str) -> Disclosure:
    return Disclosure(
        id=disc_id,
        standard=standard,
        title=title,
        category="topic",
        requirement_text="x",
        required_elements=[{"id": "e1", "desc": "d"}],
        retrieval_queries=["q"],
        suggested_fix_template="fix",
    )


def _kb():
    return {
        "2-2": _disc("2-2", "GRI 2: General Disclosures 2021", "Entities"),
        "2-10": _disc("2-10", "GRI 2: General Disclosures 2021", "Nomination"),
        "303-3": _disc("303-3", "GRI 303: Water 2018", "Water withdrawal"),
    }


def test_rows_ordered_by_natural_key():
    col = MatrixColumn(label="A", score_by_id={"2-2": 5, "2-10": 4, "303-3": 5})
    m = build_coverage_matrix(_kb(), [col])
    assert [r.code for r in m.rows] == ["GRI 2-2", "GRI 2-10", "GRI 303-3"]


def test_no_columns_yields_no_rows():
    # Nothing tested -> nothing in the sheet.
    m = build_coverage_matrix(_kb(), [])
    assert m.rows == []


def test_scores_map_to_values_with_na_and_blanks():
    # 5 -> kept; 0 -> kept (N/A sentinel, rendered "N/A" by the xlsx layer);
    # None (judge error) -> blank cell.
    col = MatrixColumn(label="A", score_by_id={"2-2": 5, "2-10": 0, "303-3": None})
    m = build_coverage_matrix(_kb(), [col])
    by_code = {r.code: r.values[0] for r in m.rows}
    assert by_code["GRI 2-2"] == 5      # graded
    assert by_code["GRI 2-10"] == 0     # N/A
    assert by_code["GRI 303-3"] is None  # error -> blank


def test_untested_disclosure_is_omitted():
    col = MatrixColumn(label="A", score_by_id={"2-2": 1})
    m = build_coverage_matrix(_kb(), [col])
    by_code = {r.code: r.values[0] for r in m.rows}
    assert by_code == {"GRI 2-2": 1}    # 303-3/2-10 untested -> omitted


def test_row_included_if_tested_in_any_column():
    cols = [
        MatrixColumn(label="A", score_by_id={"2-2": 5}),
        MatrixColumn(label="B", score_by_id={"303-3": 3}),
    ]
    m = build_coverage_matrix(_kb(), cols)
    by_code = {r.code: r.values for r in m.rows}
    assert set(by_code) == {"GRI 2-2", "GRI 303-3"}  # 2-10 untested by both -> omitted
    assert by_code["GRI 2-2"] == [5, None]    # tested in A, blank in B
    assert by_code["GRI 303-3"] == [None, 3]  # blank in A, tested in B


def test_column_labels_preserved():
    col = MatrixColumn(label="Acme v2", score_by_id={"2-2": 4})
    m = build_coverage_matrix(_kb(), [col])
    assert m.column_labels == ["Acme v2"]
