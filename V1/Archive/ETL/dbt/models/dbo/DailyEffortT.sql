-- DailyEffortT: one vessel's effort on one day, with the website's changes
-- applied, plus the columns DB167 has no room for.
--
-- 1. cleaned: DB167's rows, with the cleaning rules applied, each to a whole column:
--      R1  Trim surrounding whitespace and fold case-only spellings into the form the same research group uses most often in that column.
--      R3  "Survey Type": Survey type wording. Same category, written differently.
--      LOC-001  "Locality", CRC only: spellings that differ by more than case,
--               merged into the spelling used on the other records.
--      LOC-002  "Launch", "Locality" and "Return", CRC only: Sekiu and Seiku are
--               the same town on the Strait of Juan de Fuca, two vowels swapped.
--      GEO-001  "Sub-area", CRC only: sub-area spellings merged.
-- 2. r, s: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns, plus the ones this table adds.

{% set spelled_columns = ["Launch", "Locality", "Return", "Region", "Sub-area", "Survey Type", "Project/Objective", "Record Source"] %}
{#- R4. Distance travelled, in nautical miles, from the text and the unit
    recorded beside it. Left empty where the unit is missing or unknown. -#}
{% set distance_nm %}
    case when s."Total Distance" ~ '^\s*[0-9]+(\.[0-9]+)?\s*$'
          and lower(btrim(coalesce(s."Distance Units", ''))) in ('nm', 'nmi', 'mn', 'km', 'm')
         then round((case lower(btrim(coalesce(s."Distance Units", '')))
                         when 'km' then btrim(s."Total Distance")::numeric * 0.539957
                         when 'm'  then btrim(s."Total Distance")::numeric * 0.000539957
                         else btrim(s."Total Distance")::numeric
                     end)::numeric, 3)
    end
{% endset %}

with t as (select * from {{ source('raw', 'DailyEffortT') }}),
{{ spelling_ctes('t', spelled_columns) }},
cleaned as (
    select
        t."DailyEffortID" as "DailyEffortID",
        t."Research Group" as "Research Group",
        t."Vessel" as "Vessel",
        t."Date" as "Date",
        t."Start Time" as "Start Time",
        t."End Time" as "End Time",
        t."Distance Units" as "Distance Units",
        case when t."Research Group" = 'CRC' then regexp_replace({{ spelled("Launch") }}, 'seiku', 'Sekiu', 'gi')
             else {{ spelled("Launch") }} end as "Launch",
        case when t."Research Group" = 'CRC'
             then regexp_replace({{ mapped(spelled("Locality"), {'N Cordell Bank': 'N. Cordell Bank', "ZITTEL'S": 'Zittels',
                                                                 'Everett, N Puget Sound': 'Everett/N. Puget Sound',
                                                                 'Pt. St. George': 'Pt St George', 'Pt. St.George': 'Pt St George'}) }},
                                 'seiku', 'Sekiu', 'gi')
             else {{ spelled("Locality") }} end as "Locality",
        t."Personnel" as "Personnel",
        t."PhotoDataBy" as "PhotoDataBy",
        {{ spelled("Project/Objective") }} as "Project/Objective",
        {{ spelled("Record Source") }} as "Record Source",
        {{ spelled("Region") }} as "Region",
        case when t."Research Group" = 'CRC' then regexp_replace({{ spelled("Return") }}, 'seiku', 'Sekiu', 'gi')
             else {{ spelled("Return") }} end as "Return",
        case when t."Research Group" = 'CRC'
             then {{ mapped(spelled("Sub-area"), {'SE Alaska': 'Southeast Alaska', 'Nothern Washington': 'Northern Washington',
                                                  'Nothern Oregon': 'Northern Oregon', 'Queen Charlottes': 'Queen Charlotte Islands'}) }}
             else {{ spelled("Sub-area") }} end as "Sub-area",
        t."Survey Comments" as "Survey Comments",
        {{ mapped(spelled("Survey Type"), {'Non-Standardized Large Vessel': 'Large Vessel Non-Standardized',
                                           'Land Observation': 'Land', 'ENTANGLEMENT': 'Entanglement Response',
                                           'ENT': 'Entanglement Response', 'Uknown': 'Unknown'}) }} as "Survey Type",
        t."Time Off Effort" as "Time Off Effort",
        t."Total Distance" as "Total Distance",
        t."Total Survey Effort" as "Total Survey Effort",
        t."SourceDB" as "SourceDB",
        t."Start Dec Lat" as "Start Dec Lat",
        t."Start Dec Long" as "Start Dec Long",
        t."End Dec Lat" as "End Dec Lat",
        t."End Dec Long" as "End Dec Long",
        t."SentToAnnualDB" as "SentToAnnualDB",
        t."Finalized" as "Finalized"
    from t {{ spelling_joins('t', spelled_columns) }}
),
r as (
    {{ replay_rows('cleaned', 'DailyEffortT', 'DailyEffortID') }}
),
s as (
    select {{ replayed_columns('DailyEffortT', 'r') }}, r.__edits from r
),
-- Where each effort started and ended, and how that is known. No effort in
-- DB167 has a usable recorded position, so each is derived, in this order:
--   1. the crew's B (begin) or T (end) log entry, where it has a position
--   2. the first or last point of the effort's GPS track
--   3. start only: the day's earliest positioned log entry
-- Every pick has a complete order, so a tie is never settled by which row
-- Postgres meets first: an earlier DailyEventID or TrackID wins. An entry with
-- no time is only used where no entry has one.
begin_entry as (
    select distinct on ("DailyEffortID") "DailyEffortID" as effort,
           ST_SetSRID(ST_MakePoint("Dec Long", "Dec Lat"), 4326) as point
    from {{ ref('DailyEventT') }}
    where btrim(upper("Code")) = 'B' and "Dec Lat" is not null and "Dec Long" is not null
    order by "DailyEffortID", "Time" asc, "DailyEventID"
),
end_entry as (
    select distinct on ("DailyEffortID") "DailyEffortID" as effort,
           ST_SetSRID(ST_MakePoint("Dec Long", "Dec Lat"), 4326) as point
    from {{ ref('DailyEventT') }}
    where btrim(upper("Code")) = 'T' and "Dec Lat" is not null and "Dec Long" is not null
    order by "DailyEffortID", "Time" desc nulls last, "DailyEventID"
),
first_entry as (
    select distinct on ("DailyEffortID") "DailyEffortID" as effort,
           ST_SetSRID(ST_MakePoint("Dec Long", "Dec Lat"), 4326) as point
    from {{ ref('DailyEventT') }}
    where "Dec Lat" is not null and "Dec Long" is not null
    order by "DailyEffortID", "Time", "DailyEventID"
),
track_start as (
    select distinct on ("EffortID") "EffortID" as effort, ST_StartPoint(ST_GeometryN(geom, 1)) as point
    from {{ ref('TrackT') }} where "EffortID" is not null and geom is not null
    order by "EffortID", "TrackID"
),
track_end as (
    select distinct on ("EffortID") "EffortID" as effort,
           ST_EndPoint(ST_GeometryN(geom, ST_NumGeometries(geom))) as point
    from {{ ref('TrackT') }} where "EffortID" is not null and geom is not null
    order by "EffortID", "TrackID"
),
positions as (
    select s."DailyEffortID",
           coalesce(b.point, ts.point, f.point) as start_point,
           case when b.point is not null then 'event_B'
                when ts.point is not null then 'gps_track'
                when f.point is not null then 'first_positioned_record' end as start_coord_source,
           coalesce(t.point, te.point) as end_point,
           case when t.point is not null then 'event_T'
                when te.point is not null then 'gps_track' end as end_coord_source
    from s
    left join begin_entry b on b.effort = s."DailyEffortID"
    left join track_start ts on ts.effort = s."DailyEffortID"
    left join first_entry f on f.effort = s."DailyEffortID"
    left join end_entry t on t.effort = s."DailyEffortID"
    left join track_end te on te.effort = s."DailyEffortID"
)
select
    {{ column_list('DailyEffortT', 's') }},
    {{ edited('total_distance_nm', distance_nm, 'numeric(10,3)', 's.__edits') }} as total_distance_nm,
    {{ edited('start_point', 'p.start_point', 'geometry(Point,4326)', 's.__edits') }} as start_point,
    {{ edited('end_point', 'p.end_point', 'geometry(Point,4326)', 's.__edits') }} as end_point,
    {{ edited('start_coord_source', 'p.start_coord_source', 'text', 's.__edits') }} as start_coord_source,
    {{ edited('end_coord_source', 'p.end_coord_source', 'text', 's.__edits') }} as end_coord_source,
    {{ vessel_id('s') }} as vessel_id
from s
left join positions p on p."DailyEffortID" = s."DailyEffortID"
{{ vessel_joins('s') }}
