-- DB167's SightingEffortTrackV: each sighting with its effort and GPS track,
-- for efforts whose track file is in DB167's file list
-- (models/build/db167_track_files.sql).
select
    {%- for c in raw_column_names('SightingT') %}
       s.{{ adapter.quote(c) }} as {{ adapter.quote('Sighting_' ~ c) }},
    {%- endfor %}
       s."SightEvent" as "Sighting_SightEvent", s."OtherSpecies" as "Sighting_OtherSpecies",
       s."Sample Type" as "Sighting_Sample Type",
    {%- for c in ['DailyEffortID', 'Research Group', 'Vessel', 'Date', 'Start Time', 'End Time', 'Distance Units',
                  'Launch', 'Locality', 'Personnel', 'PhotoDataBy', 'Project/Objective', 'Record Source', 'Region',
                  'Return', 'Sub-area', 'Survey Comments', 'Survey Type', 'Time Off Effort', 'Total Distance',
                  'Total Survey Effort', 'SourceDB', 'Start Dec Lat', 'Start Dec Long', 'End Dec Lat', 'End Dec Long',
                  'TrackFileName', 'TrackFileType', 'Useable', 'HitRate', 'TrackFileSize', 'TrackComments',
                  'TrackStartTime', 'TrackEndTime', 'GPSPointCount', 'TrackDuration'] %}
       d.{{ adapter.quote(c) }} as {{ adapter.quote('Effort_' ~ c) }}{{ "," if not loop.last }}
    {%- endfor %}
from {{ ref('SightingV') }} s
join {{ ref('DailyEffortV') }} d on d."DailyEffortID" = s."DailyEffortID"
where d."TrackFileName" is not null
  and exists (select 1 from {{ ref('db167_track_files') }} f where f.name = lower(btrim(d."TrackFileName")))
