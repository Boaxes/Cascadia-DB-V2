-- Two tidy-ups that go with the admin rework.
--
-- 1. Track records linked to an effort by Doug's V1 links but left with the
--    status 'unassociated'. Their file is in storage and they are linked, so
--    they are 'available'. The site already works this out from the link and
--    the file; this makes the stored status agree. Expected: 11 rows.
--
-- 2. The old Restore wrote a second entry that reversed the first and marked
--    the first restored_by it. Undo now puts a change back and removes its
--    entry, so each such pair is removed together: the change it records is
--    no longer in effect. Checked before running: every pair cancels out, and
--    the record is as it was before the first entry of each pair.
--
-- One transaction. Run as postgres:
--   ssh root@<server> "sudo -u postgres psql -d sedb -v ON_ERROR_STOP=1" < this file

BEGIN;

DO $$
DECLARE n integer;
BEGIN
  UPDATE dbo."TrackT" SET track_status = 'available'
  WHERE  "EffortID" IS NOT NULL AND track_status = 'unassociated';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 11 THEN
    RAISE EXCEPTION 'expected 11 stale track statuses, found %', n;
  END IF;
  RAISE NOTICE 'track statuses corrected: %', n;

  -- Every restore entry must be the partner of exactly one restored entry.
  IF EXISTS (SELECT 1 FROM app.audit_log r WHERE r.action = 'restore'
             AND NOT EXISTS (SELECT 1 FROM app.audit_log o WHERE o.restored_by = r.id)) THEN
    RAISE EXCEPTION 'a restore entry has no partner; stopping';
  END IF;

  WITH pairs AS (
      SELECT id, restored_by FROM app.audit_log WHERE restored_by IS NOT NULL
  ), originals AS (
      DELETE FROM app.audit_log WHERE id IN (SELECT id FROM pairs) RETURNING id
  )
  DELETE FROM app.audit_log WHERE id IN (SELECT restored_by FROM pairs);
  GET DIAGNOSTICS n = ROW_COUNT;
  RAISE NOTICE 'restore pairs removed: %', n;

  IF EXISTS (SELECT 1 FROM app.audit_log WHERE action = 'restore' OR restored_by IS NOT NULL) THEN
    RAISE EXCEPTION 'restore entries remain; stopping';
  END IF;
END $$;

COMMIT;
