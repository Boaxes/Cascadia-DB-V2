-- Sightings: the Explore map and list, and each sighting's page. Every
-- research group. id is the hashed Primary Key; DB167's ID is
-- legacy_sighting_id, which the website's addresses use.
select id, "SightingID" as legacy_sighting_id, "Research Group" as research_group, daily_effort_id,
       "Sighting" as sighting_number, vessel_id, species_id, species_uncertain, "Species" as species_raw,
       "Date"::date as sighting_date, "Start Time" as sighting_time, "StartDateTime" as sighting_datetime,
       st_y(geom) as lat, st_x(geom) as lon, geom, "End Dec Lat" as end_lat, "End Dec Long" as end_lon, end_geom,
       "Position Type" as position_type, "Sight Type" as sight_type, "Est Size Best" as est_size_best,
       "Est Size Min" as est_size_min, "Est Size Max" as est_size_max, num_calves, "Group Beh" as group_behavior,
       "Group Type" as group_type, depth_m, "Photos?" as photos_taken, "Comments" as comments,
       identified_individual_count, "Bearing" as bearing, "Range" as range_m, "Reticle" as reticle,
       "RangeSource" as range_source, "Series Number 1" as photo_series_1, "Frames 1" as photo_frames_1,
       "Photographer 1" as photographer_1
from {{ ref('SightingT') }} s
