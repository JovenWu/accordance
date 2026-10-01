-- Remove everything scripts/seed_demo_history.sql inserted.
--
-- runs.report_id and findings.run_id are both ON DELETE CASCADE, so deleting
-- the reports is sufficient — the runs and findings go with them.
--
-- Matches on BOTH the id prefix and the name prefix. Either alone would be
-- enough; requiring both means a real report can never be caught by this even
-- if someone happens to name one "[demo] ...".

BEGIN;

DELETE FROM reports
WHERE id LIKE 'demo_rep_%'
  AND name LIKE '[demo]%';

COMMIT;
