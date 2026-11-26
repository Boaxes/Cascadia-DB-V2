-- DailyConditionT: a weather and sea-state reading during an effort, with the
-- website's changes applied, plus its point, visibility and vessel.
--
-- 1. cleaned: DB167's rows, with the cleaning rules applied, each to a whole column:
--      R1  Trim surrounding whitespace and fold case-only spellings into the form the same research group uses most often in that column. Precipitation codes are folded but never merged beyond that -- DB167 documents nowhere what they mean.
--      R7  a coordinate pair with a 0 in it, or with one half missing, is not a
--          position, and both halves are cleared.
--      CND-001  "Beaufort", CRC only: the scale runs 0 to 12. Values outside it
--               can't be recovered reliably, so they are cleared.
--      CND-003  "Quality", CRC only: valid codes are E, G, VG, F and P.
--               Anything else is cleared.
-- 2. r, s: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns, plus the ones this table adds.

{% set spelled_columns = ["Quality", "Precipitation", "Visibility"] %}
{%- set fn = adapter.quote(this.schema) %}

{#- Visibility in nautical miles. DB167 has two overlapping columns: the later
    one wins where it reads as a distance (macros/cleaning.sql,
    nautical_miles), the older one where it does not. -#}
{% set visibility_nm %}
    coalesce({{ nautical_miles('s."Visibility (nm)"') }}, {{ nautical_miles('s."Visibility"') }})
{% endset %}

with t as (select * from {{ source('raw', 'DailyConditionT') }}),
{{ spelling_ctes('t', spelled_columns) }},
cleaned as (
    select
        t."DailyConditionID" as "DailyConditionID",
        t."DailyEffortID" as "DailyEffortID",
        t."Research Group" as "Research Group",
        t."Vessel" as "Vessel",
        t."Date" as "Date",
        t."ConditionTime" as "ConditionTime",
        {{ recorded_coordinate("Dec Lat", "Dec Lat", "Dec Long") }} as "Dec Lat",
        {{ recorded_coordinate("Dec Long", "Dec Lat", "Dec Long") }} as "Dec Long",
        t."% Cloud Cover" as "% Cloud Cover",
        case when t."Research Group" = 'CRC' and (t."Beaufort" < 0 or t."Beaufort" > 12) then null
             else t."Beaufort" end as "Beaufort",
        {{ spelled("Precipitation") }} as "Precipitation",
        case when t."Research Group" = 'CRC' and btrim({{ spelled("Quality") }}) <> ''
                  and upper(btrim({{ spelled("Quality") }})) not in ('E', 'G', 'VG', 'F', 'P') then null
             else {{ spelled("Quality") }} end as "Quality",
        t."Swell" as "Swell",
        {{ spelled("Visibility") }} as "Visibility",
        t."Visibility (nm)" as "Visibility (nm)",
        t."Comments" as "Comments",
        t."SourceDB" as "SourceDB",
        t."ConditionDateTime" as "ConditionDateTime"
    from t {{ spelling_joins('t', spelled_columns) }}
),
r as (
    {{ replay_rows('cleaned', 'DailyConditionT', 'DailyConditionID') }}
),
s as (
    select {{ replayed_columns('DailyConditionT', 'r') }}, r.__edits from r
)
select
    {{ column_list('DailyConditionT', 's') }},
    {{ edited('geom', fn ~ '.point_from(s."Dec Lat", s."Dec Long")', 'geometry(Point,4326)', 's.__edits') }} as geom,
    {{ edited('visibility_nm', visibility_nm, 'numeric(8,2)', 's.__edits') }} as visibility_nm,
    {{ vessel_id('s') }} as vessel_id
from s
{{ vessel_joins('s') }}
