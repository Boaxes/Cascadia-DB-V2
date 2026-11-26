-- SightingIdentificationT: DB167's rows, with the website's changes applied, plus their vessel.
--
-- 1. cleaned: nothing in DB167's copy of this table is cleaned.
-- 2. r, s: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns, plus the ones this table adds.

with cleaned as (
    select
        "SightingIdentificationID",
        "IndividualID",
        "SightingID",
        "IdentificationID",
        "Research Group",
        "SightingDate",
        "Vessel",
        "Sighting",
        "Species",
        "CRC ID",
        "Field ID"
    from {{ source('raw', 'SightingIdentificationT') }}
),
r as (
    {{ replay_rows('cleaned', 'SightingIdentificationT', 'SightingIdentificationID') }}
),
s as (
    select {{ replayed_columns('SightingIdentificationT', 'r') }}, r.__edits from r
)
select
    {{ column_list('SightingIdentificationT', 's') }},
    {{ vessel_id('s') }} as vessel_id
from s
{{ vessel_joins('s') }}
