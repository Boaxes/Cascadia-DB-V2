-- DailyEventT: a timestamped, positioned log entry during an effort, with the
-- website's changes applied, plus its point, vessel and event code.
--
-- 1. cleaned: DB167's rows, with the cleaning rules applied, each to a whole column:
--      R1  Trim surrounding whitespace and fold case-only spellings into the form the same research group uses most often in that column.
--      R7  a coordinate pair with a 0 in it, or with one half missing, is not a
--          position, and both halves are cleared.
-- 2. r, s: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns, plus the ones this table adds.

{% set spelled_columns = ["Code", "Line", "ObsL", "ObsR", "Rec"] %}
{%- set fn = adapter.quote(this.schema) %}

with t as (select * from {{ source('raw', 'DailyEventT') }}),
{{ spelling_ctes('t', spelled_columns) }},
cleaned as (
    select
        t."DailyEventID" as "DailyEventID",
        t."DailyEffortID" as "DailyEffortID",
        t."Research Group" as "Research Group",
        t."Date" as "Date",
        t."Vessel" as "Vessel",
        t."Time" as "Time",
        {{ spelled("Code") }} as "Code",
        {{ recorded_coordinate("Dec Lat", "Dec Lat", "Dec Long") }} as "Dec Lat",
        {{ recorded_coordinate("Dec Long", "Dec Lat", "Dec Long") }} as "Dec Long",
        {{ spelled("Line") }} as "Line",
        {{ spelled("ObsL") }} as "ObsL",
        {{ spelled("ObsR") }} as "ObsR",
        {{ spelled("Rec") }} as "Rec",
        t."Comments" as "Comments",
        t."SourceDB" as "SourceDB",
        t."EventDateTime" as "EventDateTime"
    from t {{ spelling_joins('t', spelled_columns) }}
),
r as (
    {{ replay_rows('cleaned', 'DailyEventT', 'DailyEventID') }}
),
s as (
    select {{ replayed_columns('DailyEventT', 'r') }}, r.__edits from r
)
select
    {{ column_list('DailyEventT', 's') }},
    {{ edited('geom', fn ~ '.point_from(s."Dec Lat", s."Dec Long")', 'geometry(Point,4326)', 's.__edits') }} as geom,
    {{ vessel_id('s') }} as vessel_id,
    -- What the code means, from EventCodeT. Matched ignoring case and
    -- surrounding space, which is how DB167 compared them. Codes EventCodeT
    -- does not list keep no link.
    {{ edited('event_code_id', 'c."EventCodeID"', 'integer', 's.__edits') }} as event_code_id
from s
{{ vessel_joins('s') }}
left join {{ ref('EventCodeT') }} c on upper(btrim(s."Code")) = upper(c."EventCode")
