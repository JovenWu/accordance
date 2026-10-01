# Evaluation Harness

Measure how well the judge pipeline scores against hand-labeled ground truth.

## TL;DR

```bash
# From the repo root, after backend deps are installed:
python -m accordance.eval eval/ground_truth/your-report.yaml
```

Output: a markdown report under `eval/reports/<timestamp>__<report_id>.md`
plus a one-screen summary on stdout.

## Why bother

You can't improve what you can't measure. Every retrieval / prompt / model
change should be scored against the same ground-truth set so you know
whether the change actually helped, hurt, or did nothing.

Pick a few real sustainability reports, hand-label maybe 15–25 disclosures
each, and re-run the eval after every meaningful change. Trust the numbers,
not the vibes.

## Labeling a new report

1. **Get a sustainability PDF.** Use a real one (not the toy fixture). Drop
   it into `backend/data/pdfs/` (or wherever your `pdf_dir` setting points).

2. **Run it through the app once** so the pipeline has a run to compare
   against. You can use the dashboard upload or `POST /api/runs`. Once it
   completes, note the `run_id` shown in the URL.

3. **Open the run page in the dashboard** and skim each disclosure. For each
   one, decide for yourself what the *correct* verdict is. The judge's
   verdict is informational — you're labeling against the report, not the
   judge.

4. **Copy `_template.yaml`** into `eval/ground_truth/your-report.yaml` and
   fill it in:

   ```yaml
   report_id: your-report-2024
   pdf_filename: your-report.pdf
   pdf_sha256: optional-but-recommended-for-exact-match

   disclosures:
     - id: "2-1"
       expected_status: covered     # covered | partial | missing
       expected_evidence_page: 4    # optional, used for page-match metric
       elements:                    # optional — omit if you only label disclosure-level
         - id: legal_name
           expected_status: found   # found | partial | missing
           expected_page: 4
         - id: countries_of_operation
           expected_status: partial
     - id: "3-1"
       expected_status: missing
   ```

   Only label disclosures you're *confident* about — the harness compares
   exactly what you wrote and ignores the rest, so a partial set is fine.

5. **Run the eval:**

   ```bash
   python -m accordance.eval eval/ground_truth/your-report.yaml
   ```

   The runner will automatically reuse the completed run for that PDF. To
   force a fresh pipeline invocation (e.g. after changing the judge prompt),
   pass `--rerun`. To compare against a specific run instead of the
   most-recent one, pass `--use-run <run_id>`.

## Reading the report

The markdown report has:

- **Headline metrics:** disclosure-status accuracy, element-status accuracy,
  coverage gap (covered → marked missing), false-covered (missing → marked
  covered), page-match rate.
- **Confusion matrix:** rows = ground truth, columns = what the judge said.
  Diagonal is good.
- **Per-class P/R/F1:** which verdicts the judge is good at and which it
  fumbles.
- **Mismatches:** every disclosure the judge got wrong, with its evidence
  excerpt and page. This is the most useful section for diagnosis — most
  mistakes turn out to be retrieval-misses (wrong chunks reached the judge)
  rather than judging errors.
- **Not judged:** disclosures you labeled that the run never produced a
  finding for. Usually a sign the run was cancelled or the judge errored.

## CLI options

| Flag                | Effect                                                         |
|---------------------|----------------------------------------------------------------|
| `--use-run RUN_ID`  | Compare against this exact run. Overrides automatic matching. |
| `--rerun`           | Force a fresh pipeline invocation even if a run exists.        |
| `--only 2-1,3-1`    | Restrict comparison to a subset of disclosure IDs.             |
| `--output PATH`     | Write the markdown report to a custom path.                    |

## Layout

```
eval/
├── README.md                    # this file
├── ground_truth/
│   ├── _template.yaml           # commented starter
│   └── *.yaml                   # your labeled reports
└── reports/                     # generated markdown (gitignored)
```
