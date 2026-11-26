-- DB167's DailyEffortV: each CRC effort with its GPS track file's details, as
-- in DB167. The track is found by its Foreign Key daily_effort_id.
select e."DailyEffortID", e."Research Group", e."Vessel", e."Date", e."Start Time", e."End Time",
       e."Distance Units", e."Launch", e."Locality", e."Personnel", e."PhotoDataBy", e."Project/Objective",
       e."Record Source", e."Region", e."Return", e."Sub-area", e."Survey Comments", e."Survey Type",
       e."Time Off Effort", e."Total Distance", e."Total Survey Effort", e."SourceDB", e."Start Dec Lat",
       e."Start Dec Long", e."End Dec Lat", e."End Dec Long",
       t."TrackFileName", t."TrackFileType", t."Useable", t."HitRate", t."TrackFileSize",
       t."Comments" as "TrackComments", t."StartTime" as "TrackStartTime", t."EndTime" as "TrackEndTime",
       t."GPSPointCount", t."TrackDuration"
from {{ ref('DailyEffortT') }} e
left join {{ ref('TrackT') }} t on t.daily_effort_id = e.id
where e."Research Group" = 'CRC'
