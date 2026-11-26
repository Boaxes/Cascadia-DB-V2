-- SightingEventT: DB167's rows, with the website's changes applied, plus the sighting
-- each belongs to and its vessel.
--
-- 1. cleaned: nothing in DB167's copy of this table is cleaned.
-- 2. r, s: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns, plus the ones this table adds.

with cleaned as (
    select
        "SightingEventID",
        "DailyEffortID",
        "Research Group",
        "Vessel",
        "Date",
        "EventTime",
        "Sighting",
        "EventID",
        "Bearing",
        "Dec Lat",
        "Dec Long",
        "Field ID",
        "NumReact",
        "PosType",
        "Range",
        "Reaction",
        "SightEvent",
        "SightEventComments",
        "SourceDB"
    from {{ source('raw', 'SightingEventT') }}
),
r as (
    {{ replay_rows('cleaned', 'SightingEventT', 'SightingEventID') }}
),
s as (
    select {{ replayed_columns('SightingEventT', 'r') }}, r.__edits from r
),
-- DB167 has no SightingID here, only the effort and the sighting number: the
-- same key DB167's own SightingV joins on. Linked only where exactly one
-- sighting matches, and left empty otherwise.
matched as (
    select k, min("SightingID") as "SightingID"
    from (select distinct c."SightingEventID" as k, x."SightingID"
          from s c join {{ ref('SightingT') }} x
            on x."DailyEffortID" = c."DailyEffortID" and x."Sighting" = c."Sighting"
          where c."DailyEffortID" is not null and c."Sighting" is not null) matches
    group by k
    having count(*) = 1
)
select
    {{ column_list('SightingEventT', 's') }},
    {{ edited('sighting_id', 'm."SightingID"', 'integer', 's.__edits') }} as sighting_id,
    {{ vessel_id('s') }} as vessel_id
from s
left join matched m on m.k = s."SightingEventID"
{{ vessel_joins('s') }}
