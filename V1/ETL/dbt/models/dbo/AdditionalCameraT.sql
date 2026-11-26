-- AdditionalCameraT: DB167's rows, with the website's changes applied. No columns of its own.
--
-- 1. cleaned: nothing in DB167's copy of this table is cleaned.
-- 2. r: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns.

with cleaned as (
    select
        "AdditionalCameraID",
        "DailyEffortID",
        "Research Group",
        "Vessel",
        "ResearchGroupID",
        "SurveyDate",
        "VesselID",
        "SightingID",
        "SightingNum",
        "FieldIDs",
        "PhotographerID",
        "PhotographerInitials",
        "ImageSeriesName",
        "StartFrame",
        "EndFrame",
        "Notes"
    from {{ source('raw', 'AdditionalCameraT') }}
),
r as (
    {{ replay_rows('cleaned', 'AdditionalCameraT', 'AdditionalCameraID') }}
)
select {{ replayed_columns('AdditionalCameraT', 'r') }}
from r
