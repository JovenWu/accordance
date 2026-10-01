"""Markdown rendering for EvalReport.

Keeps the writer dumb — all numbers come from the EvalReport already.
"""

from __future__ import annotations

from datetime import datetime

from accordance.eval.metrics import (
    DISCLOSURE_STATUS_LABELS,
    ELEMENT_STATUS_LABELS,
    DisclosureEvalResult,
    EvalReport,
    coverage_gap,
    false_covered,
)


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _frac(num: int, denom: int) -> str:
    pct = (num / denom * 100) if denom else 0.0
    return f"{num} / {denom} ({pct:.1f}%)"


def _confusion_table(
    name: str, conf: dict[str, dict[str, int]], labels: tuple[str, ...]
) -> str:
    """Render a confusion matrix as a markdown table.

    Rows where every value is 0 AND the row label has no support are collapsed
    to a single em-dash row for readability.
    """
    header = "| " + name + " | " + " | ".join(f"`{c}`" for c in labels) + " |\n"
    sep = "|" + "---|" * (len(labels) + 1) + "\n"
    rows = []
    for r in labels:
        row_sum = sum(conf[r].values())
        cells: list[str] = []
        for c in labels:
            cells.append(str(conf[r][c]) if row_sum or conf[r][c] else "—")
        rows.append("| **" + r + "** | " + " | ".join(cells) + " |")
    return header + sep + "\n".join(rows) + "\n"


def _class_metrics_table(metrics) -> str:
    header = "| Status | P | R | F1 | Support |\n|---|---|---|---|---|\n"
    rows = []
    for m in metrics:
        if m.support == 0:
            continue  # skip classes the labeler never used
        rows.append(
            f"| `{m.label}` | {m.precision:.2f} | {m.recall:.2f} | "
            f"{m.f1:.2f} | {m.support} |"
        )
    return header + "\n".join(rows) + "\n"


def _mismatch_block(r: DisclosureEvalResult) -> str:
    parts: list[str] = [
        f"### ❌ `{r.disclosure_id}`: expected `{r.expected_status}`, got `{r.actual_status}`"
    ]
    if r.elements:
        for er in r.elements:
            if er.correct:
                parts.append(f"- Element `{er.element_id}`: ✅ `{er.actual_status}`")
            else:
                parts.append(
                    f"- Element `{er.element_id}`: ❌ expected `{er.expected_status}`,"
                    f" got `{er.actual_status}`"
                )
    if r.note:
        parts.append(f"- Judge note: {r.note}")
    if r.evidence_excerpt:
        excerpt = r.evidence_excerpt.replace("\n", " ").strip()
        if len(excerpt) > 240:
            excerpt = excerpt[:240] + "…"
        page_str = f" (page {r.actual_evidence_page})" if r.actual_evidence_page else ""
        parts.append(f"- Evidence: _{excerpt}_{page_str}")
    if r.expected_evidence_page is not None:
        ok = "✅" if r.page_match else "❌"
        parts.append(
            f"- Page: expected `{r.expected_evidence_page}`,"
            f" got `{r.actual_evidence_page}` {ok}"
        )
    if r.retrieval_hit is not None:
        ok = "✅" if r.retrieval_hit else "❌"
        pages = ", ".join(str(p) for p in r.retrieved_pages) or "(none)"
        parts.append(f"- Retrieval: surfaced pages [{pages}] {ok}")
    return "\n".join(parts) + "\n"


def render_markdown(report: EvalReport) -> str:
    gap = coverage_gap(report)
    fc = false_covered(report)
    mismatches = [r for r in report.disclosure_results if not r.correct]

    lines: list[str] = []
    lines.append(f"# Eval Report: `{report.report_id}`\n")
    lines.append(f"- **Run ID:** `{report.run_id or '(none)'}`")
    lines.append(
        f"- **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    lines.append(
        f"- **Labeled:** {report.total_disclosures_labeled} disclosures, "
        f"{report.total_elements_labeled} elements"
    )
    lines.append("")

    sc = report.system_config
    if sc is not None:
        lines.append("## System Config\n")
        lines.append("| Aspect | Value |")
        lines.append("|---|---|")
        ph_display = (
            ", ".join(f"`{h[:8]}`" for h in sc.prompt_hashes)
            if sc.prompt_hashes
            else "(none)"
        )
        models_display = (
            ", ".join(f"`{m}`" for m in sc.models) if sc.models else "(none)"
        )
        lines.append(f"| Prompt hash(es) | {ph_display} |")
        lines.append(f"| Model(s) | {models_display} |")
        lines.append(f"| Total judge calls | {sc.total_traces} |")
        lines.append(
            f"| Re-judges fired | {sc.rejudge_count} "
            f"({_pct(sc.rejudge_count / sc.total_traces) if sc.total_traces else '—'}) |"
        )
        lines.append(f"| Vision fallbacks used | {sc.vision_fallback_count} |")
        lines.append(f"| Retrieval mode | `{sc.retrieval_mode}` |")
        lines.append(
            f"| Retrieval per-element | {'yes' if sc.retrieval_per_element else 'no'} |"
        )
        rr = f"on `{sc.rerank_model}` (top-{sc.rerank_top_n})" if sc.rerank_enabled else "off"
        lines.append(f"| Reranker | {rr} |")
        lines.append(
            f"| Hallucinated excerpts cleared | {sc.hallucinated_cleared_count} |"
        )
        lines.append(f"| No-excerpt verdicts | {sc.no_excerpt_count} |")
        if sc.parse_fallback_count or sc.parse_error_count:
            lines.append(
                f"| Parse fallback / error | "
                f"{sc.parse_fallback_count} / {sc.parse_error_count} |"
            )
        lines.append("")

    lines.append("## Headline\n")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(
        f"| Disclosure status accuracy | "
        f"{_frac(report.correct_disclosures, report.total_disclosures_labeled)} |"
    )
    lines.append(
        f"| Element status accuracy | "
        f"{_frac(report.correct_elements, report.total_elements_labeled)} |"
    )
    lines.append(f"| Coverage gap (covered → missed) | {gap} |")
    lines.append(f"| False-covered (missing → hit) | {fc} |")
    if report.page_match_total:
        lines.append(
            f"| Evidence page match (±1) | "
            f"{_frac(report.page_match_count, report.page_match_total)} |"
        )
    else:
        lines.append("| Evidence page match (±1) | (no pages labeled) |")
    if report.retrieval_recall is not None:
        lines.append(
            f"| Retrieval recall@k (±1 page) | "
            f"{_frac(report.retrieval_recall_count, report.retrieval_recall_total)} |"
        )
    lines.append("")

    lines.append("## Disclosure Confusion Matrix\n")
    lines.append("Rows = expected, columns = actual.\n")
    lines.append(
        _confusion_table(
            "expected ↓ / actual →",
            report.disclosure_confusion,
            DISCLOSURE_STATUS_LABELS,
        )
    )

    lines.append("## Per-Class Metrics — Disclosure Status\n")
    lines.append(_class_metrics_table(report.disclosure_class_metrics))

    if report.total_elements_labeled:
        lines.append("## Element Confusion Matrix\n")
        lines.append(
            _confusion_table(
                "expected ↓ / actual →",
                report.element_confusion,
                ELEMENT_STATUS_LABELS,
            )
        )
        lines.append("## Per-Class Metrics — Element Status\n")
        lines.append(_class_metrics_table(report.element_class_metrics))

    if mismatches:
        lines.append(f"## Mismatches ({len(mismatches)})\n")
        for r in mismatches:
            lines.append(_mismatch_block(r))

    if report.not_judged:
        lines.append(f"## Not Judged ({len(report.not_judged)})\n")
        lines.append(
            "Disclosures the labeler scored but the run never produced a finding for. "
            "Usually means the run was cancelled mid-flight or the judge errored "
            "on every retry.\n"
        )
        for did in report.not_judged:
            lines.append(f"- `{did}`")
        lines.append("")

    if report.extra_findings:
        lines.append(f"## Extra Findings ({len(report.extra_findings)})\n")
        lines.append(
            "Findings the pipeline produced but the labeler didn't score "
            "(informational, not counted against accuracy).\n"
        )
        lines.append(", ".join(f"`{d}`" for d in sorted(report.extra_findings)))
        lines.append("")

    return "\n".join(lines)


def render_console_summary(report: EvalReport) -> str:
    """One-screen summary printed to stdout after a CLI run."""
    gap = coverage_gap(report)
    fc = false_covered(report)
    out: list[str] = []
    out.append(f"Eval: {report.report_id}  (run {report.run_id or '-'})")
    out.append(
        f"  disclosure accuracy : "
        f"{_frac(report.correct_disclosures, report.total_disclosures_labeled)}"
    )
    out.append(
        f"  element accuracy    : "
        f"{_frac(report.correct_elements, report.total_elements_labeled)}"
    )
    out.append(f"  coverage gap        : {gap}  (covered → marked missing)")
    out.append(f"  false-covered       : {fc}  (missing → marked covered)")
    if report.page_match_total:
        out.append(
            f"  page match (±1)     : "
            f"{_frac(report.page_match_count, report.page_match_total)}"
        )
    if report.retrieval_recall is not None:
        out.append(
            f"  retrieval recall@k  : "
            f"{_frac(report.retrieval_recall_count, report.retrieval_recall_total)}"
        )
    if report.not_judged:
        out.append(f"  not judged          : {len(report.not_judged)}")
    return "\n".join(out)
