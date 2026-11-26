-- SampleIdentificationT: DB167's rows, with the website's changes applied. No columns of its own.
--
-- 1. cleaned: nothing in DB167's copy of this table is cleaned.
-- 2. r: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns.

with cleaned as (
    select
        "SampleIdentificationID",
        "SightingID",
        "IdentificationID",
        "SightingDate",
        "Research Group",
        "Vessel",
        "Sighting",
        "CRC ID",
        "Field ID",
        "Sample #",
        "Sample Type",
        "Certainty of Sample ID",
        "Sampled By",
        "IndividualID"
    from {{ source('raw', 'SampleIdentificationT') }}
),
r as (
    {{ replay_rows('cleaned', 'SampleIdentificationT', 'SampleIdentificationID') }}
)
select {{ replayed_columns('SampleIdentificationT', 'r') }}
from r
