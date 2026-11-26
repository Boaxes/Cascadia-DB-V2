-- TrackingT: DB167's rows, with the website's changes applied, plus their vessel.
--
-- 1. cleaned: nothing in DB167's copy of this table is cleaned.
-- 2. r, s: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns, plus the ones this table adds.

with cleaned as (
    select
        "TrackingID",
        "DailyEffortID",
        "Research Group",
        "Vessel",
        "Date",
        "Sighting",
        "Time",
        "VesselDecLat",
        "VesselDecLong",
        "TargetDecLat",
        "TargetDecLong",
        "Angle",
        "Bearing",
        "BearingType",
        "BreachCount",
        "CalfCount",
        "Code",
        "ContactCount",
        "Depth",
        "DistBetweenSG",
        "FieldID",
        "FocalGroupSize",
        "FollowNum",
        "GenBeh",
        "GEX",
        "GEY",
        "Heading",
        "Height",
        "LogCount",
        "Orientation",
        "Range",
        "RangeSource",
        "RespCount",
        "Reticle",
        "SlapCount",
        "SpacingWithinSG",
        "SpyhopCount",
        "SubGroups",
        "SurfaceLungeCount",
        "TargetLat",
        "TargetLong",
        "TargetPosType",
        "TrackSighting",
        "TrackVessel",
        "VesselLat",
        "VesselLong",
        "TrackComments",
        "SourceDB"
    from {{ source('raw', 'TrackingT') }}
),
r as (
    {{ replay_rows('cleaned', 'TrackingT', 'TrackingID') }}
),
s as (
    select {{ replayed_columns('TrackingT', 'r') }}, r.__edits from r
)
select
    {{ column_list('TrackingT', 's') }},
    {{ vessel_id('s') }} as vessel_id
from s
{{ vessel_joins('s') }}
