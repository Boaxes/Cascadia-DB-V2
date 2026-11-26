-- IndividualT: DB167's rows, with the website's changes applied. No columns of its own.
--
-- 1. cleaned: nothing in DB167's copy of this table is cleaned.
-- 2. r: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns.

with cleaned as (
    select
        "IndividualID",
        "Species",
        "CRC ID"
    from {{ source('raw', 'IndividualT') }}
),
r as (
    {{ replay_rows('cleaned', 'IndividualT', 'IndividualID') }}
)
select {{ replayed_columns('IndividualT', 'r') }}
from r
