-- DB167's TagSummaryV: each tag deployment with its sighting's position and
-- species and its effort's place, found by the Foreign Keys.
select ts."TagSummaryID", ts."DailyEffortID", ts."Research Group", ts."Vessel", ts."Date", ts."Sighting",
       ts."Attachment", ts."CallTypes", ts."CEE", ts."DataCollected", ts."DeployBodyLoc", ts."DeployDateTime",
       ts."DeployRxn", ts."DeployTime", ts."DeployType", ts."Descriptions", ts."DiveTypes", ts."Field ID" as "Field_ID",
       ts."GPSTrackSource", ts."HoursData", ts."HoursTotal", ts."PlaybackEnd", ts."PlaybackStart", ts."PlaybackType",
       ts."PreyData", ts."RecoverDateTime", ts."Segments", ts."SonarLogFilename", ts."Tag#" as "TagNum",
       ts."TagDataFilename", ts."TagOffDateTime", ts."TagType", ts."VHFChannel", ts."Video", ts."TagComments",
       ts."SourceDB", s."Start Dec Lat", s."Start Dec Long", e."Launch", e."Locality", s."Species", s."Est Size Best"
from {{ ref('TagSummaryT') }} ts
left join {{ ref('DailyEffortT') }} e on e.id = ts.daily_effort_id
left join {{ ref('SightingT') }} s on s.id = ts.sighting_id
