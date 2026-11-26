-- DroneDeploymentT: DB167's rows, with the website's changes applied. No columns of its own.
--
-- 1. cleaned: nothing in DB167's copy of this table is cleaned.
-- 2. r: the website's edits applied on top (macros/replay.sql).
-- 3. the final select: DB167's columns.

with cleaned as (
    select
        "DroneEventID",
        "DailyEffortID",
        "Research Group",
        "DroneDate",
        "Vessel",
        "Drone",
        "SightingNum",
        "FieldID",
        "LidarUnit",
        "FlightNum",
        "LaunchTime",
        "LaunchLatitude",
        "LaunchLongitude",
        "ReturnTime",
        "ReturnLatitude",
        "ReturnLongitude",
        "StartFrame",
        "EndFrame",
        "GPSPhoto",
        "VideoFile",
        "TargetVessels",
        "Comments",
        "SerialNumber",
        "Pilot",
        "LaunchStaff",
        "CalibrationObject",
        "Description",
        "CalibrationObjectType"
    from {{ source('raw', 'DroneDeploymentT') }}
),
r as (
    {{ replay_rows('cleaned', 'DroneDeploymentT', 'DroneEventID') }}
)
select {{ replayed_columns('DroneDeploymentT', 'r') }}
from r
