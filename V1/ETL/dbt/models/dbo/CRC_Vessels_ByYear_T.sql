-- CRC_Vessels_ByYear_T: DB167's rows, with the website's changes applied. No columns of its own.
--
-- 1. cleaned: nothing in DB167's copy of this table is cleaned.
-- 2. r: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns.

with cleaned as (
    select
        "CRCVesselID",
        "Research Group",
        "Vessel",
        "EffortYear",
        "RecordCount",
        "IncludeVessel",
        "Comments",
        "FlaggedToCheck"
    from {{ source('raw', 'CRC_Vessels_ByYear_T') }}
),
r as (
    {{ replay_rows('cleaned', 'CRC_Vessels_ByYear_T', 'CRCVesselID') }}
)
select {{ replayed_columns('CRC_Vessels_ByYear_T', 'r') }}
from r
