-- Event code lookup: DB167's EventCodeT, a short display name for each code,
-- and a link from every daily event to its code.
--
-- One transaction, so it applies completely or not at all. Safe to run once
-- on a database built before this change. It was applied to the live
-- database as postgres, because the tables belonged to postgres then:
--   ssh root@<server> "sudo -u postgres psql -d sedb -v ON_ERROR_STOP=1" < this file
-- Since 2026-09-21-sedb-owns-everything.sql, sedb can run changes like this
-- itself. A rebuild from the ETL creates the
-- same thing (build_dbo.py, promote.build_event_codes, app_views.sql).

BEGIN;

-- The frozen snapshot of DB167 gains the table it was missing.
CREATE TABLE raw."EventCodeT" (
    "EventCodeID" integer NOT NULL,
    "EventCode" text,
    "CodeDescription" text,
    "SortOrder" integer,
    PRIMARY KEY ("EventCodeID")
);
INSERT INTO raw."EventCodeT" ("EventCodeID", "EventCode", "CodeDescription", "SortOrder") VALUES
    (1, 'Ac-Record', 'Make an acoustic recording', 52),
    (2, 'EchoLog-Beg', 'Begin recording echosounder datastream', 30),
    (3, 'OBS', 'Observer Rotation', 88),
    (4, 'ET', 'End Transect', 18),
    (5, 'Drone_R', 'Drone recovered', 21),
    (6, 'BT', 'Begin Transect', 15),
    (7, 'R', 'RESUME effort', 3),
    (8, 'Rec-SS', 'Recover Sound Source', 62),
    (9, 'Rec-H', 'Recover Hydrophone', 53),
    (10, 'PB-End', 'Playback End', 42),
    (11, 'C', 'General COMMENT', 7),
    (12, 'Dep-SS', 'Deploy Sound Source', 61),
    (13, 'B', 'BEGIN survey day, describe location', 1),
    (14, 'RT', 'Resume Transect', 17),
    (15, 'PB-Beg', 'Playback Begin', 41),
    (16, 'Drone_L', 'Drone Launched', 20),
    (17, 'EchoLog-End', 'End recording echosounder datastream', 31),
    (18, 'P', 'POSITION update', 6),
    (19, 'H', 'Deploy HYDROPHONE, note observations', 51),
    (20, 'O', 'Go OFF effort, state reason', 2),
    (21, 'Sample', 'Environmental or other SAMPLE, no sighting linked', 77),
    (22, 'T', 'TERMINATE effort for the day', 4),
    (23, 'TagRec', 'Recovery of a TAG from another date or vessel', 66),
    (24, 'V', 'VESSEL approach, note type and distance', 99),
    (25, 'XT', 'Break Off Transect', 16);

CREATE TABLE dbo."EventCodeT" (LIKE raw."EventCodeT" INCLUDING ALL);
INSERT INTO dbo."EventCodeT" SELECT * FROM raw."EventCodeT";

ALTER TABLE dbo."EventCodeT" ADD COLUMN name text;
UPDATE dbo."EventCodeT" c SET name = v.name
FROM (VALUES
    ('B', 'Begin'),
    ('O', 'Off effort'),
    ('R', 'Resume'),
    ('T', 'End'),
    ('P', 'Position'),
    ('C', 'Comment'),
    ('BT', 'Begin transect'),
    ('XT', 'Break off transect'),
    ('RT', 'Resume transect'),
    ('ET', 'End transect'),
    ('Drone_L', 'Drone launched'),
    ('Drone_R', 'Drone recovered'),
    ('EchoLog-Beg', 'Echosounder start'),
    ('EchoLog-End', 'Echosounder end'),
    ('PB-Beg', 'Playback start'),
    ('PB-End', 'Playback end'),
    ('H', 'Hydrophone'),
    ('Ac-Record', 'Acoustic recording'),
    ('Rec-H', 'Recover hydrophone'),
    ('Dep-SS', 'Deploy sound source'),
    ('Rec-SS', 'Recover sound source'),
    ('TagRec', 'Tag recovery'),
    ('Sample', 'Sample'),
    ('OBS', 'Observer rotation'),
    ('V', 'Vessel approach')
) AS v(code, name)
WHERE c."EventCode" = v.code;

-- A link, not a foreign key constraint: some events carry codes EventCodeT
-- does not define, and those keep an empty link rather than being touched.
ALTER TABLE dbo."DailyEventT" ADD COLUMN event_code_id integer;
CREATE INDEX ix_dailyeventt_event_code_id ON dbo."DailyEventT" (event_code_id);
UPDATE dbo."DailyEventT" e SET event_code_id = c."EventCodeID"
FROM   dbo."EventCodeT" c
WHERE  upper(btrim(e."Code")) = upper(c."EventCode");

-- The views, as in ETL/schema/app_views.sql.
CREATE OR REPLACE VIEW app.event_code AS
SELECT c."EventCodeID"     AS id,
       c."EventCode"       AS code,
       c.name,
       c."CodeDescription" AS description,
       c."SortOrder"       AS sort_order
FROM   dbo."EventCodeT" c;

CREATE OR REPLACE VIEW app.daily_event AS
SELECT v."DailyEventID"    AS id,
       v."DailyEventID"    AS legacy_daily_event_id,
       v."Research Group"  AS research_group,
       v."DailyEffortID"   AS daily_effort_id,
       v.vessel_id,
       v."Code"            AS code,
       v."EventDateTime"   AS event_datetime,
       v."Time"            AS event_time,
       ST_Y(v.geom)        AS lat,
       ST_X(v.geom)        AS lon,
       v.geom,
       v."ObsL"            AS observer_left,
       v."ObsR"            AS observer_right,
       v."Rec"             AS recorder,
       v."Comments"        AS comments,
       v.event_code_id
FROM   dbo."DailyEventT" v
WHERE  v."Research Group" = 'CRC'
WITH CHECK OPTION;

CREATE OR REPLACE VIEW app.effort_timeline AS
SELECT 'event:' || v."DailyEventID"   AS row_key,
       v."DailyEffortID"              AS daily_effort_id,
       'event'                        AS kind,
       v."EventDateTime"              AS at,
       v."DailyEventID"               AS legacy_id,
       ST_Y(v.geom) AS lat, ST_X(v.geom) AS lon, v.geom,
       -- "Begin (B)": what the code means, with the code itself.
       COALESCE((SELECT c.name || ' (' || c."EventCode" || ')'
                 FROM dbo."EventCodeT" c WHERE c."EventCodeID" = v.event_code_id),
                v."Code", 'log entry') AS label
FROM   dbo."DailyEventT" v WHERE v."Research Group" = 'CRC'
UNION ALL
SELECT 'sighting:' || s."SightingID",
       s."DailyEffortID", 'sighting', s."StartDateTime", s."SightingID",
       ST_Y(s.geom), ST_X(s.geom), s.geom,
       COALESCE((SELECT sp.common_name FROM dbo."SpeciesT" sp
                 WHERE sp.species_id = s.species_id), s."Species", 'sighting')
FROM   dbo."SightingT" s WHERE s."Research Group" = 'CRC'
UNION ALL
SELECT 'condition:' || c."DailyConditionID",
       c."DailyEffortID", 'condition', c."ConditionDateTime", c."DailyConditionID",
       ST_Y(c.geom), ST_X(c.geom), c.geom,
       'Beaufort ' || COALESCE(c."Beaufort"::text, '?')
FROM   dbo."DailyConditionT" c WHERE c."Research Group" = 'CRC';

-- The application logs in as sedb, which has full rights on every table and
-- view; the new ones match. Skipped where there is no sedb role (a local copy).
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sedb') THEN
    GRANT ALL ON raw."EventCodeT", dbo."EventCodeT", app.event_code TO sedb;
  END IF;
END $$;

COMMIT;
