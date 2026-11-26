-- DB167's own view, translated (was ETL/schema/dbo_views.sql).
{{ config(materialized='view') }}
SELECT e."DailyEffortID", e."Research Group", e."Vessel", e."Date",
       e."Start Time", e."End Time", e."Distance Units", e."Launch",
       e."Locality", e."Personnel", e."PhotoDataBy", e."Project/Objective",
       e."Record Source", e."Region", e."Return", e."Sub-area",
       e."Survey Comments", e."Survey Type", e."Time Off Effort",
       e."Total Distance", e."Total Survey Effort", e."SourceDB",
       e."Start Dec Lat", e."Start Dec Long", e."End Dec Lat", e."End Dec Long",
       t."TrackFileName", t."TrackFileType", t."Useable", t."HitRate",
       t."TrackFileSize", t."Comments" AS "TrackComments",
       t."StartTime" AS "TrackStartTime", t."EndTime" AS "TrackEndTime",
       t."GPSPointCount", t."TrackDuration"
FROM   {{ ref('DailyEffortT') }} e
LEFT JOIN {{ ref('TrackT') }} t ON e."DailyEffortID" = t."EffortID"
WHERE  e."Research Group" = 'CRC'
