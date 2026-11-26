-- PermitTakeT: DB167's rows, with the website's changes applied. No columns of its own.
--
-- 1. cleaned: nothing in DB167's copy of this table is cleaned.
-- 2. r: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns.

with cleaned as (
    select
        "PermitTakeID",
        "DailyEffortID",
        "Research Group",
        "Vessel",
        "Date",
        "Sighting",
        "ApprTakes",
        "BiopTakes",
        "DartTagTakes",
        "Permit",
        "SCTagTakes",
        "SoundTakes",
        "UWTakes",
        "Comments",
        "SourceDB"
    from {{ source('raw', 'PermitTakeT') }}
),
r as (
    {{ replay_rows('cleaned', 'PermitTakeT', 'PermitTakeID') }}
)
select {{ replayed_columns('PermitTakeT', 'r') }}
from r
