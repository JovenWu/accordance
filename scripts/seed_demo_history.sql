BEGIN;

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
