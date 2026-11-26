{{ config(materialized='updatable_view', meta={'check_option': true}) }}
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
FROM   {{ ref('DailyEffortT') }} e
WHERE  e."Research Group" = 'CRC'
