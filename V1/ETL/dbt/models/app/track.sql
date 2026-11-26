-- GPS tracks on the map and each effort's page. Every research group. The
-- effort is the Foreign Key daily_effort_id, pointing at DailyEffortT.id.
select "TrackID" as id, "TrackID" as legacy_track_id, "Research Group" as research_group, daily_effort_id,
       file_name as object_key, track_status, vessel_id,
       (select s."Source" from {{ ref('SourceT') }} s where s."SourceID" = t."SourceID") as track_source,
       (select c."TrackCompleteCode" from {{ ref('TrackCompleteCodeT') }} c
        where c."TrackCompleteCodeID" = t."TrackCompleteCodeID") as track_complete_code,
       "SurveyDate" as survey_date, coalesce("Useable", true) as useable, geom, point_count,
       "StartTime" as start_time_utc, "EndTime" as end_time_utc, length_nm, "Comments" as comments
from {{ ref('TrackT') }} t
