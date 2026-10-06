BEGIN;

DELETE FROM reports
WHERE id LIKE 'demo_rep_%'
  AND name LIKE '[demo]%';

COMMIT;
