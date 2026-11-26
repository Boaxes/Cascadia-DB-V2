{{ config(materialized='updatable_view', meta={'check_option': true}) }}
SELECT t."TrackID"          AS id,
       t."TrackID"          AS legacy_track_id,
       t."Research Group"   AS research_group,
       t."EffortID"         AS daily_effort_id,
       t.file_name          AS object_key,
       t.track_status,
       t.vessel_id,
       (SELECT s."Source" FROM {{ ref('SourceT') }} s
         WHERE s."SourceID" = t."SourceID")            AS track_source,
       (SELECT c."TrackCompleteCode" FROM {{ ref('TrackCompleteCodeT') }} c
         WHERE c."TrackCompleteCodeID" = t."TrackCompleteCodeID") AS track_complete_code,
       t."SurveyDate"       AS survey_date,
       COALESCE(t."Useable", true) AS useable,
       t.geom,
       t.point_count,
       t."StartTime"        AS start_time_utc,
       t."EndTime"          AS end_time_utc,
       t.length_nm,
       t."Comments"         AS comments
FROM   {{ ref('TrackT') }} t
-- Tracks carry a research group on only some rows, and an unassociated file has
-- none at all, so filtering them out would hide exactly the ones the track tool
-- exists to resolve.
WHERE  t."Research Group" IS NULL OR t."Research Group" = 'CRC'
