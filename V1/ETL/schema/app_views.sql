-- What Django reads and writes.
--
-- Every view draws from exactly one dbo table, with no join, GROUP BY, DISTINCT
-- or window function, so Postgres updates it directly and a write from the
-- application passes straight through to the table underneath. Where a value
-- has to come from somewhere else it is a scalar subquery in the select list,
-- which keeps that property (those columns are read-only, which is correct --
-- they are lookups).
--
-- WHERE research_group = 'CRC' is the one place the CRC filter lives. dbo holds
-- every organisation's records; this is what makes the application Cascadia's.
-- WITH CHECK OPTION stops a write creating a row the view could not see.
--
-- Column names here are lowercase and free of punctuation: this is the single
-- point where DB167's names are translated, so Django never sees a quoted
-- identifier.

DROP VIEW IF EXISTS app.effort_timeline, app.sample, app.daily_event, app.event_code,
    app.daily_condition, app.sighting, app.track, app.daily_effort,
    app.vessel, app.species CASCADE;

CREATE VIEW app.species AS
SELECT sp.species_id AS id,
       sp.code,
       sp.common_name,
       sp.scientific_name,
       sp.category
FROM   dbo."SpeciesT" sp
-- Only codes CRC actually recorded. dbo holds every organisation's, and a
-- filter listing all 94 would offer species Cascadia has never seen.
WHERE  EXISTS (SELECT 1 FROM dbo."SightingT" s
               WHERE s.species_id = sp.species_id AND s."Research Group" = 'CRC');

CREATE VIEW app.vessel AS
SELECT vessel_id       AS id,
       legacy_vessel_id,
       COALESCE(code, vessel_text)  AS code,
       COALESCE(name, vessel_text)  AS name
FROM   dbo."VesselListT" v
-- Only vessels CRC worked from, on the same reasoning.
WHERE  EXISTS (SELECT 1 FROM dbo."DailyEffortT" e
               WHERE e.vessel_id = v.vessel_id AND e."Research Group" = 'CRC')
   OR  EXISTS (SELECT 1 FROM dbo."SightingT" s
               WHERE s.vessel_id = v.vessel_id AND s."Research Group" = 'CRC');

CREATE VIEW app.daily_effort AS
SELECT e."DailyEffortID"        AS id,
       e."DailyEffortID"        AS legacy_daily_effort_id,
       e."Research Group"       AS research_group,
       e."Date"::date           AS effort_date,
       e."Start Time"           AS start_time,
       e."End Time"             AS end_time,
       e.vessel_id,
       e."Locality"             AS locality,
       e."Launch"               AS launch,
       e."Return"               AS return_location,
       e."Survey Type"          AS survey_type,
       e."Region"               AS region,
       e."Sub-area"             AS sub_area,
       e."Project/Objective"    AS project_objective,
       e."Personnel"            AS personnel,
       e."Survey Comments"      AS survey_comments,
       -- DB167 types these as a clock time; they are durations, and the
       -- application formats them as such.
       e."Time Off Effort"::interval     AS time_off_effort,
       e."Total Survey Effort"::interval AS total_survey_effort,
       e.total_distance_nm      AS distance_recorded_nm,
       ST_Y(e.start_point)      AS start_lat,
       ST_X(e.start_point)      AS start_lon,
       e.start_point,
       e.start_coord_source,
       ST_Y(e.end_point)        AS end_lat,
       ST_X(e.end_point)        AS end_lon,
       e.end_point,
       e.end_coord_source
FROM   dbo."DailyEffortT" e
WHERE  e."Research Group" = 'CRC'
WITH CHECK OPTION;

CREATE VIEW app.sighting AS
SELECT s."SightingID"       AS id,
       s."SightingID"       AS legacy_sighting_id,
       s."Research Group"   AS research_group,
       s."DailyEffortID"    AS daily_effort_id,
       s."Sighting"         AS sighting_number,
       s.vessel_id,
       s.species_id,
       s.species_uncertain,
       s."Species"          AS species_raw,
       s."Date"::date       AS sighting_date,
       s."Start Time"       AS sighting_time,
       s."StartDateTime"    AS sighting_datetime,
       ST_Y(s.geom)         AS lat,
       ST_X(s.geom)         AS lon,
       s.geom,
       s."End Dec Lat"      AS end_lat,
       s."End Dec Long"     AS end_lon,
       s.end_geom,
       s."Position Type"    AS position_type,
       s."Sight Type"       AS sight_type,
       s."Est Size Best"    AS est_size_best,
       s."Est Size Min"     AS est_size_min,
       s."Est Size Max"     AS est_size_max,
       s.num_calves,
       s."Group Beh"        AS group_behavior,
       s."Group Type"       AS group_type,
       s.depth_m,
       s."Photos?"          AS photos_taken,
       s."Comments"         AS comments,
       s.identified_individual_count,
       -- Offered as optional columns on an export. V1 kept these in a JSON
       -- blob because its import did not carry them; they are plain columns.
       s."Bearing"          AS bearing,
       s."Range"            AS range_m,
       s."Reticle"          AS reticle,
       s."RangeSource"      AS range_source,
       s."Series Number 1"  AS photo_series_1,
       s."Frames 1"         AS photo_frames_1,
       s."Photographer 1"   AS photographer_1
FROM   dbo."SightingT" s
WHERE  s."Research Group" = 'CRC'
WITH CHECK OPTION;

CREATE VIEW app.track AS
SELECT t."TrackID"          AS id,
       t."TrackID"          AS legacy_track_id,
       t."Research Group"   AS research_group,
       t."EffortID"         AS daily_effort_id,
       t.file_name          AS object_key,
       t.track_status,
       t.vessel_id,
       (SELECT s."Source" FROM dbo."SourceT" s
         WHERE s."SourceID" = t."SourceID")            AS track_source,
       (SELECT c."TrackCompleteCode" FROM dbo."TrackCompleteCodeT" c
         WHERE c."TrackCompleteCodeID" = t."TrackCompleteCodeID") AS track_complete_code,
       t."SurveyDate"       AS survey_date,
       COALESCE(t."Useable", true) AS useable,
       t.geom,
       t.point_count,
       t."StartTime"        AS start_time_utc,
       t."EndTime"          AS end_time_utc,
       t.length_nm,
       t."Comments"         AS comments
FROM   dbo."TrackT" t
-- Tracks carry a research group on only some rows, and an unassociated file has
-- none at all, so filtering them out would hide exactly the ones the track tool
-- exists to resolve.
WHERE  t."Research Group" IS NULL OR t."Research Group" = 'CRC'
WITH CHECK OPTION;

CREATE VIEW app.daily_condition AS
SELECT c."DailyConditionID"  AS id,
       c."DailyConditionID"  AS legacy_daily_condition_id,
       c."Research Group"    AS research_group,
       c."DailyEffortID"     AS daily_effort_id,
       c.vessel_id,
       c."ConditionDateTime" AS condition_datetime,
       c."ConditionTime"     AS condition_time,
       ST_Y(c.geom)          AS lat,
       ST_X(c.geom)          AS lon,
       c.geom,
       c."Beaufort"          AS beaufort,
       c."Swell"             AS swell_ft,
       c."% Cloud Cover"     AS cloud_cover_pct,
       c."Precipitation"     AS precipitation,
       c."Quality"           AS quality,
       c.visibility_nm,
       c."Comments"          AS comments
FROM   dbo."DailyConditionT" c
WHERE  c."Research Group" = 'CRC'
WITH CHECK OPTION;

-- What a daily event's code means. DB167's EventCodeT, plus a short name.
CREATE VIEW app.event_code AS
SELECT c."EventCodeID"     AS id,
       c."EventCode"       AS code,
       c.name,
       c."CodeDescription" AS description,
       c."SortOrder"       AS sort_order
FROM   dbo."EventCodeT" c;

CREATE VIEW app.daily_event AS
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

CREATE VIEW app.sample AS
SELECT s."SampleID"        AS id,
       s."SampleID"        AS legacy_sample_id,
       s."Research Group"  AS research_group,
       s."SightingID"      AS sighting_id,
       s."DailyEffortID"   AS daily_effort_id,
       s.vessel_id,
       s.species_id,
       COALESCE(s."Sample #", s."Sample Number") AS sample_number,
       s."Sample Type"     AS sample_type,
       -- The model wants one timestamp; DB167 keeps the day and the time apart.
       (s."Date"::date + COALESCE(s."SampleTime", '00:00'::time)) AS sample_datetime,
       s."Certainty of Sample ID" AS certainty_of_id,
       s."Preservation"    AS preservation,
       s."Sampled by"      AS sampled_by,
       s."Field ID"        AS field_id,
       s."Reaction"        AS reaction,
       s."Comments"        AS comments
FROM   dbo."SampleT" s
WHERE  s."Research Group" = 'CRC'
WITH CHECK OPTION;

-- The one read-only view. A UNION, so Postgres cannot update it, which is
-- correct: it is three tables shown as one sequence of what happened that day.
--
-- row_key is synthetic because the three branches share no key space -- V1 used
-- a plain row_id and Django treated it as a primary key, which it was not.
CREATE VIEW app.effort_timeline AS
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
