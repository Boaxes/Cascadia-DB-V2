-- EffortProblemT: DB167's rows, with the website's changes applied. No columns of its own.
--
-- 1. cleaned: nothing in DB167's copy of this table is cleaned.
-- 2. r: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns.

with cleaned as (
    select
        "ProblemID",
        "Research Group",
        "EffortDate",
        "RecSource",
        "DailyEffortNum",
        "ThisVessel",
        "PreferredRecordSource",
        "PreferredVesselName",
        "PreferredResearchGroup",
        "Comments",
        "LinkedProblemID",
        "MissingInAnnualUnionDB",
        "MissingInIanDB",
        "OriginalRG",
        "OriginalVessel",
        "FixedByUserID"
    from {{ source('raw', 'EffortProblemT') }}
),
r as (
    {{ replay_rows('cleaned', 'EffortProblemT', 'ProblemID') }}
)
select {{ replayed_columns('EffortProblemT', 'r') }}
from r
