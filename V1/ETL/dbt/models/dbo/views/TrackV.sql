-- DB167's TrackV: each GPS track with the names of its device type, research
-- group, vessel (from DB167's VesselT, models/build/db167_vessels.sql) and
-- completeness code.
select t."TrackID", t."EffortID", t."ResearchGroupID", t."TrackCompleteCodeID", t."VesselID", t."SourceID",
       t."SurveyDate", t."TrackFileName", t."TrackFileType", t."Useable", t."HitRate", t."TrackFileSize",
       t."Comments", t."StartTime", t."EndTime", t."GPSPointCount", t."TrackDuration",
       s."Source", rg."Code" as "Research Group", v."VesselName", v."VesselCode", tc."TrackCompleteCode"
from {{ ref('TrackT') }} t
left join {{ ref('SourceT') }} s on s."SourceID" = t."SourceID"
left join {{ ref('ResearchGroupT') }} rg on rg."ResearchGroupID" = t."ResearchGroupID"
left join {{ ref('db167_vessels') }} v on v."VesselID" = t."VesselID"
left join {{ ref('TrackCompleteCodeT') }} tc on tc."TrackCompleteCodeID" = t."TrackCompleteCodeID"
