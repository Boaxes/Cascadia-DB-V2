-- A map point is always drawn from the coordinates beside it: never stale,
-- never from anywhere else.
select 'SightingT' as table_name, "SightingID"::text as id from {{ ref('SightingT') }}
where geom is distinct from dbo_next.point_from("Start Dec Lat", "Start Dec Long")
   or end_geom is distinct from dbo_next.point_from("End Dec Lat", "End Dec Long")
union all
select 'DailyConditionT', "DailyConditionID"::text from {{ ref('DailyConditionT') }}
where geom is distinct from dbo_next.point_from("Dec Lat", "Dec Long")
union all
select 'DailyEventT', "DailyEventID"::text from {{ ref('DailyEventT') }}
where geom is distinct from dbo_next.point_from("Dec Lat", "Dec Long")
