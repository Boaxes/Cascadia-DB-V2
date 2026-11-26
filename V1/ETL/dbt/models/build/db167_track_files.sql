-- DB167's TrackFileList, the track files it knows of, read as dbo.SightingEffortTrackV
-- compares them. A copy rather than a view of raw, so no view depends on raw
-- and ETL/import_raw.py can replace it.
select distinct lower(btrim("FileName")) as name from {{ source('raw', 'TrackFileList') }}
where "FileName" is not null
