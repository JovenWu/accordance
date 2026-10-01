-- Throwaway history rows so the paginated/searchable history list has enough
-- data to exercise. DEV ONLY.
--
-- Everything is tagged two ways so removal is unambiguous:
--   * report id  LIKE 'demo_rep_%'
--   * report name LIKE '[demo]%'
--
-- Deliberately does NOT touch run_completions or llm_usage: those drive the
-- per-user PDF count and $-spent dashboards, and fake rows there would corrupt
-- real spend figures. Only reports/runs/findings are seeded, which is all the
-- history list reads.
--
-- Remove with scripts/unseed_demo_history.sql (FKs cascade, so deleting the
-- reports takes the runs and findings with them).

BEGIN;

-- 100 reports -> 11 pages at 10/page, enough for the ellipsis windowing to
-- actually appear (it only kicks in past 7 pages).
INSERT INTO reports (id, name, created_by, created_at)
SELECT
    'demo_rep_' || lpad(i::text, 3, '0'),
    '[demo] '
        || (ARRAY['Astra International','Bank Mandiri','Telkom Indonesia',
                  'Unilever Indonesia','Pertamina','Adaro Energy','Vale Indonesia',
                  'Bank BRI','Indofood','Semen Indonesia','Aneka Tambang',
                  'Chandra Asri','Bukit Asam','Kalbe Farma','Sinar Mas',
                  'Wijaya Karya','Pupuk Indonesia','Timah','Bio Farma',
                  'Garuda Indonesia'])[1 + (i % 20)]
        || ' Sustainability Report ' || (2020 + (i % 6))::text || '.pdf',
    1,
    now() - (i || ' days')::interval
FROM generate_series(1, 100) AS i;

-- One run per report. Every 7th keeps a DIFFERENT pdf_filename from the report
-- name, standing in for a report renamed after upload — that is the case where
-- searching only one of the two columns would strand the user.
INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, pdf_sha256,
                  pdf_path, status, uploaded_at, completed_at, created_by)
SELECT
    'demo_run_' || substr(r.id, 10) || '_v1',
    r.id,
    1,
    'initial',
    CASE WHEN (substr(r.id, 10)::int % 7) = 0
         THEN 'original-upload-' || substr(r.id, 10) || '.pdf'
         ELSE r.name END,
    'demo_sha_' || substr(r.id, 10),
    'demo.pdf',
    (ARRAY['completed','completed','completed','completed','completed',
           'failed','cancelled'])[1 + (substr(r.id, 10)::int % 7)],
    r.created_at,
    r.created_at + interval '4 minutes',
    1
FROM reports r
WHERE r.id LIKE 'demo_rep_%';

-- A second version on every 3rd report, so the "N versions" label varies and
-- the latest-run join has something to actually choose between.
INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, pdf_sha256,
                  pdf_path, status, uploaded_at, completed_at, created_by)
SELECT
    'demo_run_' || substr(r.id, 10) || '_v2',
    r.id, 2, 'retry', r.name, 'demo_sha_' || substr(r.id, 10),
    'demo.pdf', 'completed',
    r.created_at + interval '1 hour',
    r.created_at + interval '1 hour 5 minutes',
    1
FROM reports r
WHERE r.id LIKE 'demo_rep_%' AND (substr(r.id, 10)::int % 3) = 0;

-- 12 findings per run with a mixed status spread, so the covered/partial/missing
-- counters on each row show varied numbers instead of three zeros.
INSERT INTO findings (run_id, disclosure_id, standard, status, note,
                      elements_json, suggested_fix, score)
SELECT
    run.id,
    '2-' || d::text,
    'GRI 2',
    (ARRAY['covered','covered','covered','covered','covered','covered',
           'partial','partial','partial','missing','missing','missing'])[d],
    'demo finding',
    '[]',
    'demo fix',
    (ARRAY[5,5,4,4,5,4,3,2,3,1,1,0])[d]
FROM runs run
CROSS JOIN generate_series(1, 12) AS d
WHERE run.id LIKE 'demo_run_%';

COMMIT;
