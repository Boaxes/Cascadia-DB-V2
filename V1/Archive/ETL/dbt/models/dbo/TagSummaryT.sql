-- TagSummaryT: DB167's rows, with the website's changes applied, plus their vessel.
--
-- 1. cleaned: nothing in DB167's copy of this table is cleaned.
-- 2. r, s: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns, plus the ones this table adds.

with cleaned as (
    select
        "TagSummaryID",
        "DailyEffortID",
        "Research Group",
        "Vessel",
        "Date",
        "Sighting",
        "Attachment",
        "CallTypes",
        "CEE",
        "DataCollected",
        "DeployBodyLoc",
        "DeployDateTime",
        "DeployRxn",
        "DeployTime",
        "DeployType",
        "Descriptions",
        "DiveTypes",
        "Field ID",
        "GPSTrackSource",
        "HoursData",
        "HoursTotal",
        "PlaybackEnd",
        "PlaybackStart",
        "PlaybackType",
        "PreyData",
        "RecoverDateTime",
        "Segments",
        "SonarLogFilename",
        "Tag#",
        "TagDataFilename",
        "TagOffDateTime",
        "TagType",
        "VHFChannel",
        "Video",
        "TagComments",
        "SourceDB",
        "Playback"
    from {{ source('raw', 'TagSummaryT') }}
),
r as (
    {{ replay_rows('cleaned', 'TagSummaryT', 'TagSummaryID') }}
),
s as (
    select {{ replayed_columns('TagSummaryT', 'r') }}, r.__edits from r
)
select
    {{ column_list('TagSummaryT', 's') }},
    {{ vessel_id('s') }} as vessel_id
from s
{{ vessel_joins('s') }}
