-- An effort's start and end are real positions in Cascadia's waters: within
-- range, and west of Greenwich.
select "DailyEffortID", 'start' as which from {{ ref('DailyEffortT') }}
where start_point is not null
  and (ST_Y(start_point) not between -90 and 90 or ST_X(start_point) not between -180 and 0)
union all
select "DailyEffortID", 'end' from {{ ref('DailyEffortT') }}
where end_point is not null
  and (ST_Y(end_point) not between -90 and 90 or ST_X(end_point) not between -180 and 0)
