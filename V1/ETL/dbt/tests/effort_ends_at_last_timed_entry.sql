-- Where an effort's end comes from its crew's T (end) entries, it is the
-- position of the latest one with a time. An entry with no time is only used
-- where no T entry has one.
with last_timed as (
    select distinct on ("DailyEffortID") "DailyEffortID",
           ST_SetSRID(ST_MakePoint("Dec Long", "Dec Lat"), 4326) as point
    from {{ ref('DailyEventT') }}
    where btrim(upper("Code")) = 'T' and "Dec Lat" is not null and "Dec Long" is not null
      and "Time" is not null
    order by "DailyEffortID", "Time" desc, "DailyEventID"
)
select e."DailyEffortID"
from {{ ref('DailyEffortT') }} e
join last_timed t on t."DailyEffortID" = e."DailyEffortID"
where e.end_coord_source = 'event_T' and not ST_Equals(e.end_point, t.point)
