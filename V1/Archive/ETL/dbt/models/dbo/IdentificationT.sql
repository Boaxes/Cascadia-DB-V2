-- IdentificationT: DB167's rows, with the website's changes applied, plus their vessel.
--
-- 1. cleaned: nothing in DB167's copy of this table is cleaned.
-- 2. r, s: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns, plus the ones this table adds.

with cleaned as (
    select
        "IdentificationID",
        "DailyEffortID",
        "SightingID",
        "IndividualID",
        "Research Group",
        "Vessel",
        "Date",
        "Sighting",
        "Beh Role",
        "Best Fluke",
        "Best Left",
        "Best Right",
        "Best Tail Stock",
        "Biopsy Photo",
        "Category",
        "CRC ID",
        "Field ID",
        "FieldID",
        "ForeLeft",
        "ForeRight",
        "HW ID",
        "MatchNotes",
        "MeasureAngle",
        "MeasureImage",
        "Other ID",
        "Qual F",
        "Qual L",
        "Qual R",
        "Record Type",
        "Scarring",
        "Scarring&Injury",
        "ScarringInjury",
        "Tag #",
        "Tag Photo",
        "Tag Type",
        "TagType",
        "TempID",
        "Comments",
        "SourceDB",
        "Species"
    from {{ source('raw', 'IdentificationT') }}
),
r as (
    {{ replay_rows('cleaned', 'IdentificationT', 'IdentificationID') }}
),
s as (
    select {{ replayed_columns('IdentificationT', 'r') }}, r.__edits from r
)
select
    {{ column_list('IdentificationT', 's') }},
    {{ vessel_id('s') }} as vessel_id
from s
{{ vessel_joins('s') }}
