-- DB167's own view, translated (was ETL/schema/dbo_views.sql).
{{ config(materialized='view') }}
SELECT ts."TagSummaryID", ts."DailyEffortID", ts."Research Group", ts."Vessel",
       ts."Date", ts."Sighting", ts."Attachment", ts."CallTypes", ts."CEE",
       ts."DataCollected", ts."DeployBodyLoc", ts."DeployDateTime",
       ts."DeployRxn", ts."DeployTime", ts."DeployType", ts."Descriptions",
       ts."DiveTypes", ts."Field ID" AS "Field_ID", ts."GPSTrackSource",
       ts."HoursData", ts."HoursTotal", ts."PlaybackEnd", ts."PlaybackStart",
       ts."PlaybackType", ts."PreyData", ts."RecoverDateTime", ts."Segments",
       ts."SonarLogFilename", ts."Tag#" AS "TagNum", ts."TagDataFilename",
       ts."TagOffDateTime", ts."TagType", ts."VHFChannel", ts."Video",
       ts."TagComments", ts."SourceDB", s."Start Dec Lat", s."Start Dec Long",
       e."Launch", e."Locality", s."Species", s."Est Size Best"
FROM   {{ ref('TagSummaryT') }} ts
LEFT JOIN {{ ref('DailyEffortT') }} e ON ts."DailyEffortID" = e."DailyEffortID"
LEFT JOIN {{ ref('SightingT') }} s
       ON ts."Research Group" = s."Research Group" AND ts."Vessel" = s."Vessel"
      AND ts."Date" = s."Date" AND ts."Sighting" = s."Sighting"
