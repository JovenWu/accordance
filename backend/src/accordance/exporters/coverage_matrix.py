from dataclasses import dataclass

from accordance.kb.ordering import natural_key
from accordance.kb.schema import Disclosure


@dataclass(frozen=True)
class MatrixColumn:
    label: str
    score_by_id: dict[str, int | None]


@dataclass(frozen=True)
class CoverageRow:
    standard: str
    code: str
    indicator: str
    values: list[int | None]


@dataclass(frozen=True)
class CoverageMatrix:
    column_labels: list[str]
    rows: list[CoverageRow]


def build_coverage_matrix(
    kb: dict[str, Disclosure], columns: list[MatrixColumn]
) -> CoverageMatrix:
    """Build a disclosure x column 0-5 grade matrix.

    A KB disclosure becomes a row if at least one column judged it (its id
    appears in some column's score_by_id). Rows are ordered by natural
    disclosure id (which clusters by standard, since each standard owns a unique
    numeric prefix). Each cell is that column's 0-5 grade for the disclosure
    (0 = Not Applicable), or None when the column did not judge it or the judge
    errored.

    The coverage score is NOT precomputed here — the xlsx exporter emits it as a
    live Excel formula (Total score / (Disclosures checked * 5)), so the
    spreadsheet recalculates if a cell is edited.
    """
    tested_ids: set[str] = set()
    for col in columns:
        tested_ids.update(col.score_by_id)

    ordered = [
        d
        for d in sorted(kb.values(), key=lambda d: natural_key(d.id))
        if d.id in tested_ids
    ]

    rows: list[CoverageRow] = []
    for d in ordered:
        values = [col.score_by_id.get(d.id) for col in columns]
        rows.append(
            CoverageRow(
                standard=d.standard,
                code=f"GRI {d.id}",
                indicator=d.title,
                values=values,
            )
        )

    return CoverageMatrix(column_labels=[c.label for c in columns], rows=rows)
