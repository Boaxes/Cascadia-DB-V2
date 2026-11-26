-- CollaboratorT: DB167's rows, with the website's changes applied. No columns of its own.
--
-- 1. cleaned: nothing in DB167's copy of this table is cleaned.
-- 2. r: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns.

with cleaned as (
    select
        "CollaboratorID",
        "Collaborator"
    from {{ source('raw', 'CollaboratorT') }}
),
r as (
    {{ replay_rows('cleaned', 'CollaboratorT', 'CollaboratorID') }}
)
select {{ replayed_columns('CollaboratorT', 'r') }}
from r
