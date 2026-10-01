"""CLI entry point: ``python -m accordance.eval <ground_truth.yaml> [options]``."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from accordance.eval.report import render_console_summary, render_markdown
from accordance.eval.runner import evaluate


def _default_output_path(report_id: str) -> Path:
    # Repo root is two dirs up from this file (backend/src/accordance/eval/__main__.py
    # → repo/backend/src/accordance/eval → repo/backend → repo). We're four parents up.
    repo_root = Path(__file__).resolve().parents[4]
    reports_dir = repo_root / "eval" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return reports_dir / f"{ts}__{report_id}.md"


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to cp1252; the console summary contains unicode
    # (e.g. "→"). Force utf-8 so printing it doesn't crash after the report is
    # already written.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    p = argparse.ArgumentParser(
        prog="python -m accordance.eval",
        description=(
            "Score a hand-labeled ground-truth file against a pipeline run. "
            "Reuses the most recent matching run when one exists; pass --rerun "
            "to force a fresh pipeline invocation."
        ),
    )
    p.add_argument("ground_truth", type=Path, help="Path to a ground-truth YAML file.")
    p.add_argument(
        "--use-run",
        metavar="RUN_ID",
        help="Compare against this exact run_id. Overrides automatic matching.",
    )
    p.add_argument(
        "--rerun",
        action="store_true",
        help="Force a fresh pipeline run even if a matching completed run exists.",
    )
    p.add_argument(
        "--only",
        metavar="IDS",
        help="Comma-separated list of disclosure IDs to restrict comparison to (e.g. 2-1,3-1).",
    )
    p.add_argument(
        "--output",
        type=Path,
        help="Path to write the markdown report to. Defaults to eval/reports/<ts>__<report_id>.md.",
    )
    args = p.parse_args(argv)

    if not args.ground_truth.exists():
        print(f"error: ground truth file not found: {args.ground_truth}", file=sys.stderr)
        return 2

    only = [s.strip() for s in args.only.split(",") if s.strip()] if args.only else None

    try:
        report = evaluate(
            args.ground_truth,
            use_run=args.use_run,
            rerun=args.rerun,
            only=only,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    output = args.output or _default_output_path(report.report_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(report), encoding="utf-8")

    print(render_console_summary(report))
    print(f"\nFull report written to: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
