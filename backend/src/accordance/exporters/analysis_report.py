"""Analysis-report PDF — one A4 page summarising a completed run.

Styled on the app's design tokens (zinc palette, Inter-like Helvetica, the
5→1 grade ramp). PyMuPDF draws everything directly — no extra dependency.
"""

from dataclasses import dataclass, field
from datetime import datetime

import fitz  # PyMuPDF

# Site palette (frontend/src/index.css), normalized to 0-1.
INK = (0.094, 0.094, 0.106)       # #18181b
MUTED = (0.443, 0.443, 0.478)     # #71717a
LINE = (0.894, 0.894, 0.906)      # #e4e4e7
SOFT = (0.949, 0.949, 0.953)      # #f5f5f5-ish card fill
ACCENT = (1.000, 0.769, 0.000)    # #ffc400
ACCENT_SOFT = (1.000, 0.965, 0.850)
ACCENT_DEEP = (0.631, 0.384, 0.027)  # #a16207 — text/icons on light fills

GRADES = {
    5: (0.090, 0.788, 0.392),     # success
    4: (0.486, 0.702, 0.259),     # lime
    3: (0.961, 0.647, 0.141),     # warning
    2: (0.976, 0.451, 0.086),     # orange
    1: (1.000, 0.220, 0.235),     # danger
}
NA_GRAY = (0.631, 0.631, 0.667)   # #a1a1aa — N/A + not assessed

GRADE_LABELS = {5: "Complete", 4: "Substantial", 3: "Partial", 2: "Minimal", 1: "Not found"}

W, H = 595, 842   # A4 portrait, points
M = 46            # page margin


@dataclass
class StandardSummary:
    name: str
    assessed: int        # findings with a non-None score (incl. N/A)
    scored: int          # applicable only (1-5)
    avg: float | None    # mean of 1-5 scores
    coverage: float | None  # sum / (scored*5), matches the XLSX footer


@dataclass
class AnalysisReport:
    report_name: str
    version: int
    pdf_filename: str
    run_id: str
    pdf_sha256: str
    completed_at: datetime | None
    page_count: int
    dist: dict[int, int]          # score -> count (0 = N/A)
    errors: int                   # judged but errored (no score)
    coverage: float | None        # whole-run coverage 0-1
    avg: float | None             # whole-run mean of 1-5
    standards: list[StandardSummary] = field(default_factory=list)


def _text(page, rect, s, font="helv", size=9, color=INK, align=0):
    # insert_textbox draws NOTHING when the rect can't hold one line (line
    # height ≈ 1.7× fontsize in MuPDF's metrics) — text anchors at the top, so
    # expanding downward is always safe.
    r = fitz.Rect(*rect)
    if r.height < size * 1.7:
        r.y1 = r.y0 + size * 1.7
    page.insert_textbox(
        r, s, fontname=font, fontsize=size, color=color, align=align
    )


def _chip(page, x, y, label, size=7.5):
    """Small rounded label chip; returns its width."""
    w = fitz.get_text_length(label, fontname="hebo", fontsize=size) + 12
    page.draw_rect(fitz.Rect(x, y, x + w, y + 14), fill=ACCENT_SOFT,
                   color=None, radius=0.5)
    _text(page, (x, y + 1.5, x + w, y + 15), label, font="hebo", size=size,
          color=ACCENT_DEEP, align=1)
    return w


def _coverage_color(pct: float | None):
    if pct is None:
        return NA_GRAY
    if pct >= 0.8:
        return GRADES[5]
    if pct >= 0.6:
        return GRADES[4]
    if pct >= 0.4:
        return GRADES[3]
    if pct >= 0.2:
        return GRADES[2]
    return GRADES[1]


def analysis_report_bytes(data: AnalysisReport) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)
    cw = W - 2 * M   # content width

    # --- Header: wordmark + report chip -------------------------------
    _text(page, (M, 42, M + 200, 56), "ACCORDANCE", font="hebo", size=11, color=INK)
    _text(page, (M, 56, M + 260, 70), "Automated disclosure coverage assessment",
          size=8, color=MUTED)
    _chip(page, W - M - 96, 46, "ANALYSIS REPORT")

    page.draw_line(fitz.Point(M, 78), fitz.Point(W - M, 78), color=LINE, width=0.75)

    # --- Title block ---------------------------------------------------------
    _text(page, (M, 92, W - M, 104), "GRI DISCLOSURE COVERAGE", font="hebo",
          size=8.5, color=MUTED)
    # Report name shrinks if it needs more than 2 lines; last resort truncates.
    title_rect = fitz.Rect(M, 106, W - M, 160)
    for size in (18, 15, 13):
        if page.insert_textbox(
            title_rect, data.report_name, fontname="hebo", fontsize=size, color=INK
        ) > 0:
            break
    else:
        page.insert_textbox(
            title_rect, data.report_name[:110].rstrip() + "...",
            fontname="hebo", fontsize=13, color=INK,
        )
    v_w = _chip(page, M, 162, f"v{data.version}")
    done = data.completed_at.strftime("%B %d, %Y") if data.completed_at else "-"
    _text(page, (M + v_w + 8, 163, W - M, 178),
          f"Completed · assessed {done}", size=8.5, color=MUTED)
    _text(page, (M, 182, W - M, 210), data.pdf_filename, size=8, color=MUTED)

    # --- Stat cards ------------------------------------------------------------
    y0, card_h, gap = 206, 58, 10
    cw4 = (cw - 3 * gap) / 4
    stats = [
        (
            f"{data.coverage * 100:.0f}%" if data.coverage is not None else "-",
            "Coverage score",
            _coverage_color(data.coverage),
        ),
        (str(sum(data.dist.values())), "Disclosures assessed", INK),
        (f"{data.avg:.1f} / 5" if data.avg is not None else "-", "Average grade", INK),
        (str(data.page_count) if data.page_count else "-", "Pages analysed", INK),
    ]
    for i, (value, label, color) in enumerate(stats):
        x = M + i * (cw4 + gap)
        page.draw_rect(fitz.Rect(x, y0, x + cw4, y0 + card_h),
                       fill=SOFT, color=LINE, width=0.5, radius=0.12)
        _text(page, (x + 10, y0 + 9, x + cw4 - 8, y0 + 38), value,
              font="hebo", size=16, color=color)
        _text(page, (x + 10, y0 + 38, x + cw4 - 8, y0 + 54), label,
              size=7.5, color=MUTED)

    # --- Grade distribution -----------------------------------------------------
    y = y0 + card_h + 24
    _text(page, (M, y, W - M, y + 12), "Grade distribution", font="hebo",
          size=9, color=INK)
    bar_y, bar_h = y + 18, 12
    total = sum(data.dist.values()) + data.errors
    order = [5, 4, 3, 2, 1, 0]
    segs = [(s, data.dist.get(s, 0)) for s in order] + ([(-1, data.errors)] if data.errors else [])
    x = M
    if total > 0:
        for s, n in segs:
            if n == 0:
                continue
            w = cw * n / total
            color = NA_GRAY if s in (0, -1) else GRADES[s]
            page.draw_rect(fitz.Rect(x, bar_y, x + w, bar_y + bar_h),
                           fill=color, color=None)
            x += w
    else:
        page.draw_rect(fitz.Rect(M, bar_y, M + cw, bar_y + bar_h),
                       fill=SOFT, color=None)
    # Legend: colored square + label · count.
    lx = M
    ly = bar_y + bar_h + 10
    for s, n in segs:
        if n == 0:
            continue
        name = "N/A" if s == 0 else ("Not assessed" if s == -1 else f"{s} {GRADE_LABELS[s]}")
        color = NA_GRAY if s in (0, -1) else GRADES[s]
        page.draw_rect(fitz.Rect(lx, ly, lx + 6, ly + 6), fill=color,
                       color=None, radius=0.3)
        label = f"{name} · {n}"
        tw = fitz.get_text_length(label, fontname="helv", fontsize=7.5)
        _text(page, (lx + 9, ly - 1, lx + 9 + tw + 4, ly + 9), label, size=7.5, color=MUTED)
        lx += 9 + tw + 14

    # --- Coverage by standard ---------------------------------------------------
    y = ly + 24
    _text(page, (M, y, W - M, y + 12), "Coverage by standard", font="hebo",
          size=9, color=INK)
    y += 16
    # Column geometry
    c_std, c_ass, c_avg, c_cov = M, M + cw - 216, M + cw - 120, M + cw - 56
    _text(page, (c_std + 8, y, c_ass, y + 10), "STANDARD", font="hebo", size=7, color=MUTED)
    _text(page, (c_ass, y, c_avg, y + 10), "ASSESSED", font="hebo", size=7, color=MUTED, align=1)
    _text(page, (c_avg, y, c_cov, y + 10), "AVG", font="hebo", size=7, color=MUTED, align=1)
    _text(page, (c_cov, y, W - M, y + 10), "COVERAGE", font="hebo", size=7, color=MUTED, align=1)
    y += 12
    page.draw_line(fitz.Point(M, y), fitz.Point(W - M, y), color=LINE, width=0.5)
    MAX_ROWS = 10
    for i, st in enumerate(data.standards[:MAX_ROWS]):
        ry = y + i * 16 + 4
        if i % 2 == 1:
            page.draw_rect(fitz.Rect(M, y + i * 16, W - M, y + (i + 1) * 16),
                           fill=SOFT, color=None)
        _text(page, (c_std + 8, ry, c_ass - 4, ry + 10), st.name, size=8, color=INK)
        _text(page, (c_ass, ry, c_avg, ry + 10), str(st.assessed), size=8, color=INK, align=1)
        _text(page, (c_avg, ry, c_cov, ry + 10),
              f"{st.avg:.1f}" if st.avg is not None else "-", size=8, color=INK, align=1)
        cov = f"{st.coverage * 100:.0f}%" if st.coverage is not None else "-"
        _text(page, (c_cov - 14, ry, W - M - 8, ry + 10), cov, font="hebo", size=8,
              color=_coverage_color(st.coverage), align=1)
    n_shown = min(len(data.standards), MAX_ROWS)
    y += n_shown * 16
    if len(data.standards) > MAX_ROWS:
        _text(page, (c_std + 8, y + 4, W - M, y + 14),
              f"... and {len(data.standards) - MAX_ROWS} more standards",
              size=7.5, color=MUTED)
        y += 16
    page.draw_line(fitz.Point(M, y), fitz.Point(W - M, y), color=LINE, width=0.5)

    # --- Methodology -----------------------------------------------------------
    y += 18
    _text(page, (M, y, W - M, y + 12), "METHODOLOGY", font="hebo",
          size=7.5, color=MUTED)
    _text(page, (M, y + 14, W - M, y + 58),
          "The report was parsed, indexed and each selected GRI disclosure was "
          "graded 0-5 against its required elements using evidence found in the "
          "document. Assessor corrections, where present, are reflected in the "
          "scores above. Coverage = total score / (applicable disclosures x 5).",
          size=8, color=MUTED)

    # --- Verification: anchored just above the footer -------------------------
    fy = H - 52
    box_h = 86
    y = fy - 18 - box_h
    page.draw_rect(fitz.Rect(M, y, W - M, y + box_h),
                   fill=(1, 1, 1), color=LINE, width=0.75, radius=0.1)
    _text(page, (M + 12, y + 8, M + 200, y + 20), "VERIFICATION", font="hebo",
          size=7.5, color=MUTED)
    rows = [
        ("Run ID", data.run_id),
        ("Document SHA-256", data.pdf_sha256),
        ("Completed", data.completed_at.strftime("%Y-%m-%d %H:%M UTC")
            if data.completed_at else "-"),
    ]
    ry = y + 24
    for label, val in rows:
        _text(page, (M + 12, ry, M + 130, ry + 12), label, size=8, color=MUTED)
        _text(page, (M + 130, ry, W - M - 12, ry + 12), val, font="cour",
              size=7.5, color=INK)
        ry += 13
    _text(page, (M + 12, ry, M + 130, ry + 12), "Live record", size=8, color=MUTED)
    _text(page, (M + 130, ry, W - M - 12, ry + 12),
          f"accordance.joven.dev/runs/{data.run_id}", size=7.5, color=ACCENT_DEEP)

    # --- Footer -------------------------------------------------------------------
    page.draw_line(fitz.Point(M, fy), fitz.Point(W - M, fy), color=LINE, width=0.5)
    _text(page, (M, fy + 8, W - M, fy + 20),
          "Automated, evidence-linked screening against GRI disclosure requirements - "
          "indicative coverage, not an assurance opinion.",
          size=7.5, color=MUTED)
    gen = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    _text(page, (M, fy + 20, W - M, fy + 32),
          f"Generated by Accordance · {gen}", size=7, color=MUTED)
    _text(page, (W - M - 60, fy + 20, W - M, fy + 32), "Page 1 of 1", size=7,
          color=MUTED, align=2)

    return doc.tobytes(garbage=4, deflate=True)
