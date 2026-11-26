-- Removes the Audit Log entries the old import wrote.
--
-- The Audit Log holds only changes people made on the website. The old import
-- wrote 88 entries of its own, under the actors 'legacy-cleanup' (87) and
-- 'Data pipeline' (1): spelling fixes, Region fixes, positions cleared, two
-- crew records and six tracks left out, and track 1266 matched to effort
-- 10016. The data pipeline now makes every one of those corrections itself
-- on each build (the Data Pipeline page lists them), so the entries are
-- deleted. Nothing in the data changes.
--
-- Run it before the first build of the new pipeline. It can be run again: a
-- second run finds nothing and deletes nothing. One transaction. Run as
-- postgres:
--   ssh root@<server> "sudo -u postgres psql -d sedb -v ON_ERROR_STOP=1" < this file

BEGIN;

DO $$
DECLARE n integer;
BEGIN
  -- Nothing should point at these entries, but clear it first so the delete cannot fail.
  UPDATE app.audit_log SET restored_by = NULL
  WHERE  restored_by IN (SELECT id FROM app.audit_log
                         WHERE actor_name IN ('legacy-cleanup', 'Data pipeline'));

  DELETE FROM app.audit_log WHERE actor_name IN ('legacy-cleanup', 'Data pipeline');
  GET DIAGNOSTICS n = ROW_COUNT;
  RAISE NOTICE 'old import entries deleted: %', n;
END $$;

COMMIT;
