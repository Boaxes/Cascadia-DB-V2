-- Weather readings on each effort's page. Every research group.
select id, "DailyConditionID" as legacy_daily_condition_id, "Research Group" as research_group,
       daily_effort_id, vessel_id, "ConditionDateTime" as condition_datetime, "ConditionTime" as condition_time,
       st_y(geom) as lat, st_x(geom) as lon, geom, "Beaufort" as beaufort, "Swell" as swell_ft,
       "% Cloud Cover" as cloud_cover_pct, "Precipitation" as precipitation, "Quality" as quality,
       visibility_nm, "Comments" as comments
from {{ ref('DailyConditionT') }} c
