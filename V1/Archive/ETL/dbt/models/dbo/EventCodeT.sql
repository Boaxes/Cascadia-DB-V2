-- EventCodeT: what each daily event code means, from DB167, plus a short name
-- for display from ref.event_code. DB167's descriptions are instructions to
-- the crew ("BEGIN survey day, describe location"), so each code also gets a
-- name. Matched exactly on the code.
--
-- 1. cleaned: nothing in DB167's copy of this table is cleaned.
-- 2. r, s: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns, plus the ones this table adds.

with cleaned as (
    select
        "EventCodeID",
        "EventCode",
        "CodeDescription",
        "SortOrder"
    from {{ source('raw', 'EventCodeT') }}
),
r as (
    {{ replay_rows('cleaned', 'EventCodeT', 'EventCodeID') }}
),
s as (
    select {{ replayed_columns('EventCodeT', 'r') }}, r.__edits from r
)
select
    {{ column_list('EventCodeT', 's') }},
    {{ edited('name', 'n.name', 'text', 's.__edits') }} as name
from s
left join {{ source('raw', 'event_code_name') }} n on n.code = s."EventCode"
