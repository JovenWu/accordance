import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from accordance.exporters.coverage_matrix import CoverageMatrix

_LABEL_COLS = 3  # Standard, KODE, INDIKATOR

_HEADER_FILL = PatternFill("solid", fgColor="1F2937")  # slate-800
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_CENTER = Alignment(horizontal="center", vertical="center")
_LEFT = Alignment(horizontal="left", vertical="center")
_SCORE_FMT = "0"  # integer 0-5 grade / counts
_COVERAGE_FMT = "0.0%"  # coverage score shown as a percentage
_NA = "N/A"  # how a 0 (Not Applicable) grade is rendered in a cell

# Excel/Sheets treat a cell starting with any of these as a formula (DDE /
# HYPERLINK / WEBSERVICE exfiltration, legacy command exec).
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _safe(value):
    """Neutralize spreadsheet formula injection in a user-controlled string.

    Report names (column labels) and KB-derived labels (standard / code /
    indicator) flow into cells, and these exports are shared with assessors, so
    a value beginning with a formula trigger is prefixed with a single quote to
    force literal text. Non-str (and empty) values pass through unchanged — the
    server-authored footer formulas are written separately and stay live.
    """
    if isinstance(value, str) and value.startswith(_FORMULA_TRIGGERS):
        return "'" + value
    return value


def to_xlsx_bytes(matrix: CoverageMatrix) -> bytes:
    """Render a CoverageMatrix as a polished .xlsx worksheet (bytes).

    Each data cell holds the disclosure's 0-5 grade (0 rendered as "N/A");
    blanks are disclosures a column did not judge. A three-row footer per
    column carries LIVE Excel formulas — not precomputed values:

      Total score          =SUM(<grades>)        (1-5 cells; N/A text + blanks ignored)
      Disclosures checked  =COUNT(<grades>)       (applicable 1-5 cells only)
      Coverage score       =Total/(Checked*5)     (shown as %; matches the app's Completeness %)

    N/A and un-judged disclosures never drag the coverage score down — the
    denominator counts only applicable (1-5) disclosures, mirroring the
    dashboard's completeness metric.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "GRI Coverage"

    n_label = _LABEL_COLS
    n_cols = n_label + len(matrix.column_labels)

    # Header row. Column labels are report names (user-controlled) -> neutralize.
    ws.append(["Standard", "KODE", "INDIKATOR", *(_safe(c) for c in matrix.column_labels)])
    for col in range(1, n_cols + 1):
        cell = ws.cell(1, col)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = _CENTER if col > n_label else _LEFT

    # Data rows: 0 -> "N/A" (text), 1-5 -> int, None -> blank.
    first_data = 2
    for row in matrix.rows:
        # standard / code / indicator are KB-derived strings -> neutralize.
        ws.append([_safe(row.standard), _safe(row.code), _safe(row.indicator)])
        r = ws.max_row
        for j, v in enumerate(row.values):
            c = ws.cell(r, n_label + 1 + j)
            if v is None:
                continue  # blank: column didn't judge this disclosure / errored
            if v == 0:
                c.value = _NA
            else:
                c.value = v
                c.number_format = _SCORE_FMT
            c.alignment = _CENTER
    last_data = ws.max_row  # == 1 when there are no data rows
    have_data = len(matrix.rows) > 0

    # Footer: three rows of live per-column formulas.
    total_row = last_data + 1
    checked_row = last_data + 2
    coverage_row = last_data + 3
    ws.cell(total_row, n_label, "Total score")
    ws.cell(checked_row, n_label, "Disclosures checked")
    ws.cell(coverage_row, n_label, "Coverage score")

    for j in range(len(matrix.column_labels)):
        col = n_label + 1 + j
        letter = get_column_letter(col)
        if have_data:
            rng = f"{letter}{first_data}:{letter}{last_data}"
            ws.cell(total_row, col).value = f"=SUM({rng})"
            ws.cell(checked_row, col).value = f"=COUNT({rng})"
            ws.cell(coverage_row, col).value = (
                f'=IF({letter}{checked_row}=0,"",'
                f"{letter}{total_row}/({letter}{checked_row}*5))"
            )
        else:
            ws.cell(total_row, col).value = 0
            ws.cell(checked_row, col).value = 0
            ws.cell(coverage_row, col).value = ""
        ws.cell(total_row, col).number_format = _SCORE_FMT
        ws.cell(checked_row, col).number_format = _SCORE_FMT
        ws.cell(coverage_row, col).number_format = _COVERAGE_FMT
        for rr in (total_row, checked_row, coverage_row):
            ws.cell(rr, col).alignment = _CENTER

    # Bold the footer; top border on the first footer row sets it apart.
    top_border = Border(top=Side(style="thin", color="9CA3AF"))
    for col in range(1, n_cols + 1):
        ws.cell(total_row, col).border = top_border
        for rr in (total_row, checked_row, coverage_row):
            ws.cell(rr, col).font = Font(bold=True)

    # Column widths: wide label columns, compact value columns.
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 50
    for col in range(n_label + 1, n_cols + 1):
        ws.column_dimensions[get_column_letter(col)].width = 16

    # Autofilter over header + data rows only (exclude the 3 footer rows).
    filter_last = last_data if have_data else 1
    ws.auto_filter.ref = f"A1:{get_column_letter(n_cols)}{filter_last}"

    # Keep the header row and the three label columns visible while scrolling.
    ws.freeze_panes = "D2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
