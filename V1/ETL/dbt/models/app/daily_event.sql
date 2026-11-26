-- The day log on each effort's page. Every research group.
select id, "DailyEventID" as legacy_daily_event_id, "Research Group" as research_group, daily_effort_id,
       vessel_id, "Code" as code, "EventDateTime" as event_datetime, "Time" as event_time,
       st_y(geom) as lat, st_x(geom) as lon, geom, "ObsL" as observer_left, "ObsR" as observer_right,
       "Rec" as recorder, "Comments" as comments, event_code_id
from {{ ref('DailyEventT') }} v
