-- DailyEffortT: efforts, with the hashed Primary Key (Research Group, Vessel
-- and Date), the website's edits, and Foreign Keys to the research group and
-- vessel. The calculated columns:
--   total_distance_nm   Total Distance in nautical miles, from its unit, unless
--                       the website set it
--   start_point, end_point and where each came from: the crew's B (begin) or
--   T (end) day-log entry with a position (the earliest B, the latest T),
--   else the first point of the effort's first GPS track (the lowest TrackID)
--   or the last point of its last (the highest TrackID), else (start only)
--   the day's earliest positioned entry. Day-log entries at the same time
--   are told apart by their hashed id, which every entry has, one the website
--   created too, so no pick depends on the order Postgres reads rows in.
{%- set distance_nm %}
    case when s."Total Distance" ~ '^\s*[0-9]+(\.[0-9]+)?\s*$'
          and lower(btrim(coalesce(s."Distance Units", ''))) in ('nm', 'nmi', 'mn', 'km', 'm')
         then round((case lower(btrim(coalesce(s."Distance Units", '')))
                         when 'km' then btrim(s."Total Distance")::numeric * 0.539957
                         when 'm'  then btrim(s."Total Distance")::numeric * 0.000539957
                         else btrim(s."Total Distance")::numeric
                     end)::numeric, 3)
    end
{%- endset %}
with {{ replayed('DailyEffortT') }},
events as (
    select id, daily_effort_id, "Code", "Time", geom
    from {{ ref('DailyEventT') }}
    where daily_effort_id is not null and geom is not null
),
begin_entry as (
    select distinct on (daily_effort_id) daily_effort_id, geom as point
    from events where upper("Code") = 'B'
    order by daily_effort_id, "Time" asc, id
),
end_entry as (
    select distinct on (daily_effort_id) daily_effort_id, geom as point
    from events where upper("Code") = 'T'
    order by daily_effort_id, "Time" desc nulls last, id
),
first_entry as (
    select distinct on (daily_effort_id) daily_effort_id, geom as point
    from events
    order by daily_effort_id, "Time", id
),
track_start as (
    select distinct on (daily_effort_id) daily_effort_id, ST_StartPoint(ST_GeometryN(geom, 1)) as point
    from {{ ref('TrackT') }} where daily_effort_id is not null and geom is not null
    order by daily_effort_id, "TrackID"
),
track_end as (
    select distinct on (daily_effort_id) daily_effort_id,
           ST_EndPoint(ST_GeometryN(geom, ST_NumGeometries(geom))) as point
    from {{ ref('TrackT') }} where daily_effort_id is not null and geom is not null
    order by daily_effort_id, "TrackID" desc
)
select s.id, {{ column_list('DailyEffortT', 's') }},
       rg.id::integer as research_group_id,
       vk.vessel_id::integer as vessel_id,
       {{ edited('total_distance_nm', distance_nm, 'numeric(10,3)', 's.__edits') }} as total_distance_nm,
       coalesce(b.point, ts.point, f.point)::geometry(Point, 4326) as start_point,
       coalesce(t.point, te.point)::geometry(Point, 4326) as end_point,
       case when b.point is not null then 'event_B'
            when ts.point is not null then 'gps_track'
            when f.point is not null then 'first_positioned_record' end as start_coord_source,
       case when t.point is not null then 'event_T'
            when te.point is not null then 'gps_track' end as end_coord_source
from s
left join begin_entry b on b.daily_effort_id = s.id
left join track_start ts on ts.daily_effort_id = s.id
left join first_entry f on f.daily_effort_id = s.id
left join end_entry t on t.daily_effort_id = s.id
left join track_end te on te.daily_effort_id = s.id
{{ group_and_vessel_joins('s') }}
