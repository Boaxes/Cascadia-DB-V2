-- DB167's own view, translated (was ETL/schema/dbo_views.sql).
{{ config(materialized='view') }}
SELECT t."TrackID", t."EffortID", t."ResearchGroupID", t."TrackCompleteCodeID",
       t."VesselID", t."SourceID", t."SurveyDate", t."TrackFileName",
       t."TrackFileType", t."Useable", t."HitRate", t."TrackFileSize",
       t."Comments", t."StartTime", t."EndTime", t."GPSPointCount",
       t."TrackDuration", s."Source", rg."Code" AS "Research Group",
       v."VesselName", v."VesselCode", tc."TrackCompleteCode"
FROM   {{ ref('TrackT') }} t
LEFT JOIN {{ ref('SourceT') }} s ON t."SourceID" = s."SourceID"
LEFT JOIN {{ ref('ResearchGroupT') }} rg ON t."ResearchGroupID" = rg."ResearchGroupID"
LEFT JOIN {{ ref('VesselT') }} v ON t."VesselID" = v."VesselID"
LEFT JOIN {{ ref('TrackCompleteCodeT') }} tc ON t."TrackCompleteCodeID" = tc."TrackCompleteCodeID"
