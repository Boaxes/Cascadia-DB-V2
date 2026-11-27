-- Queries behind every number in data-profile.md and synthetic-data-profile.md.
-- Run with DuckDB 2.x from the repo root, with the spatial extension loaded:
--   python scratch/profile/run_queries.py docs/schema/profile_queries.sql
-- Each query starts with a "-- name:" line; data-profile.md cites queries by that name.
-- Per-column summaries (type, min, max, distinct count, null share, small value lists) come from
-- DuckDB's SUMMARIZE on every file in Data/Postgres/app, Data/Postgres/dbo and Data/MnID.

-- name: row_counts
select 'sighting' as entity, count(*) as n from 'Data/Postgres/app/sighting.parquet'
union all select 'daily_effort', count(*) from 'Data/Postgres/app/daily_effort.parquet'
union all select 'daily_condition', count(*) from 'Data/Postgres/app/daily_condition.parquet'
union all select 'daily_event', count(*) from 'Data/Postgres/app/daily_event.parquet'
union all select 'track', count(*) from 'Data/Postgres/app/track.parquet'
union all select 'sample', count(*) from 'Data/Postgres/app/sample.parquet'
union all select 'identification', count(*) from 'Data/Postgres/dbo/IdentificationT.parquet'
union all select 'individual', count(*) from 'Data/Postgres/dbo/IndividualT.parquet'
union all select 'species', count(*) from 'Data/Postgres/app/species.parquet'
union all select 'vessel', count(*) from 'Data/Postgres/app/vessel.parquet'
union all select 'research_group', count(*) from 'Data/Postgres/dbo/ResearchGroupT.parquet'
union all select 'event_code', count(*) from 'Data/Postgres/app/event_code.parquet'
union all select 'mnid_sighting', count(*) from 'Data/MnID/mn_id_sightings.parquet'
union all select 'mnid_individual', count(*) from 'Data/MnID/mn_id_summary.parquet'
union all select 'mnid_sample', count(*) from 'Data/MnID/mn_id_samples.parquet'
union all select 'mnid_alias', count(*) from 'Data/MnID/crc_mn_alias_list.parquet'
union all select 'mnid_retired', count(*) from 'Data/MnID/retired_crc_ids.parquet';

-- name: key_uniqueness
select 'sighting.id' as key, count(*) as n, count(distinct id) as distinct_n from 'Data/Postgres/app/sighting.parquet'
union all select 'sighting.legacy_sighting_id', count(*), count(distinct legacy_sighting_id) from 'Data/Postgres/app/sighting.parquet'
union all select 'daily_effort.id', count(*), count(distinct id) from 'Data/Postgres/app/daily_effort.parquet'
union all select 'daily_effort.legacy_daily_effort_id', count(*), count(distinct legacy_daily_effort_id) from 'Data/Postgres/app/daily_effort.parquet'
union all select 'track.id', count(*), count(distinct id) from 'Data/Postgres/app/track.parquet'
union all select 'track.object_key', count(*), count(distinct object_key) from 'Data/Postgres/app/track.parquet'
union all select 'sample.legacy_sample_id', count(*), count(distinct legacy_sample_id) from 'Data/Postgres/app/sample.parquet'
union all select 'sample.sample_number', count(sample_number), count(distinct sample_number) from 'Data/Postgres/app/sample.parquet'
union all select 'identification.IdentificationID', count(*), count(distinct IdentificationID) from 'Data/Postgres/dbo/IdentificationT.parquet'
union all select 'individual.IndividualID', count(*), count(distinct IndividualID) from 'Data/Postgres/dbo/IndividualT.parquet'
union all select 'individual.(species,CRC ID)', count("CRC ID"), count(distinct (species_id, "CRC ID")) from 'Data/Postgres/dbo/IndividualT.parquet'
union all select 'mnid_sighting.CRC_Record', count(*), count(distinct CRC_Record) from 'Data/MnID/mn_id_sightings.parquet'
union all select 'mnid_sighting.PK_MnSightings', count(*), count(distinct PK_MnSightings) from 'Data/MnID/mn_id_sightings.parquet'
union all select 'mnid_summary.CRC_ID', count(*), count(distinct CRC_ID) from 'Data/MnID/mn_id_summary.parquet'
union all select 'mnid_sample.Sample_Number', count(*), count(distinct Sample_Number) from 'Data/MnID/mn_id_samples.parquet';

-- name: sighting_natural_key
-- How often (research group, vessel, date, sighting number) repeats: V1's human key for a sighting.
select dup_size, count(*) as groups from (
  select count(*) as dup_size from 'Data/Postgres/app/sighting.parquet'
  group by research_group, vessel_id, sighting_date, sighting_number) group by 1 order by 1;

-- name: effort_natural_key
select dup_size, count(*) as groups from (
  select count(*) as dup_size from 'Data/Postgres/app/daily_effort.parquet'
  group by research_group, vessel_id, effort_date) group by 1 order by 1;

-- name: sightings_without_effort
select count(*) filter (where daily_effort_id is null) as no_effort,
       count(*) filter (where lat is null) as no_position,
       count(*) filter (where species_id is null) as no_species,
       count(*) filter (where sighting_time is null) as no_time,
       count(*) as total
from 'Data/Postgres/app/sighting.parquet';

-- name: sightings_per_effort
select quantile_cont(n, [0.5, 0.9, 0.99]) as p50_p90_p99, max(n) as max_n, avg(n) as mean_n from (
  select daily_effort_id, count(*) as n from 'Data/Postgres/app/sighting.parquet'
  where daily_effort_id is not null group by 1);

-- name: efforts_without_sightings
select count(*) as efforts, count(*) filter (where s.daily_effort_id is null) as without_sightings
from 'Data/Postgres/app/daily_effort.parquet' e
left join (select distinct daily_effort_id from 'Data/Postgres/app/sighting.parquet') s on s.daily_effort_id = e.id;

-- name: date_spans
select 'sighting' as entity, min(sighting_date) as first, max(sighting_date) as last,
       count(*) filter (where sighting_date = date '1950-01-01') as placeholder_1950 from 'Data/Postgres/app/sighting.parquet'
union all select 'daily_effort', min(effort_date), max(effort_date), count(*) filter (where effort_date = date '1950-01-01') from 'Data/Postgres/app/daily_effort.parquet'
union all select 'track', min(survey_date), max(survey_date), 0 from 'Data/Postgres/app/track.parquet'
union all select 'sample', min(sample_datetime)::date, max(sample_datetime)::date, 0 from 'Data/Postgres/app/sample.parquet'
union all select 'mnid_sighting', min(Date)::date, max(Date)::date, 0 from 'Data/MnID/mn_id_sightings.parquet';

-- name: sightings_by_decade
select (year(sighting_date) // 10) * 10 as decade, count(*) as n from 'Data/Postgres/app/sighting.parquet' group by 1 order by 1;

-- name: sightings_by_year_recent
select year(sighting_date) as yr, count(*) as sightings, count(distinct daily_effort_id) as efforts
from 'Data/Postgres/app/sighting.parquet' where sighting_date >= date '2010-01-01' group by 1 order by 1;

-- name: sightings_by_month
select month(sighting_date) as month, count(*) as n, round(100.0 * count(*) / sum(count(*)) over (), 1) as pct
from 'Data/Postgres/app/sighting.parquet' group by 1 order by 1;

-- name: efforts_by_month
select month(effort_date) as month, count(*) as n, round(100.0 * count(*) / sum(count(*)) over (), 1) as pct
from 'Data/Postgres/app/daily_effort.parquet' group by 1 order by 1;

-- name: species_mix
select coalesce(sp.common_name, '(none)') as species, sp.category, count(*) as n,
       round(100.0 * count(*) / sum(count(*)) over (), 2) as pct
from 'Data/Postgres/app/sighting.parquet' s left join 'Data/Postgres/app/species.parquet' sp on sp.id = s.species_id
group by 1, 2 order by n desc limit 25;

-- name: group_size_by_species
select sp.common_name, count(*) as n, quantile_cont(est_size_best, [0.5, 0.9, 0.99]) as p50_p90_p99, max(est_size_best) as max_size
from 'Data/Postgres/app/sighting.parquet' s join 'Data/Postgres/app/species.parquet' sp on sp.id = s.species_id
where est_size_best is not null group by 1 order by n desc limit 12;

-- name: research_group_mix
select research_group, count(*) as sightings, round(100.0 * count(*) / sum(count(*)) over (), 2) as pct
from 'Data/Postgres/app/sighting.parquet' group by 1 order by 2 desc limit 15;

-- name: research_group_codes
-- Codes that look like typos or people's names rather than group codes.
select count(*) as codes,
       count(*) filter (where ResearchGroup is not null) as with_full_name,
       count(*) filter (where Code like '% %') as with_space
from 'Data/Postgres/dbo/ResearchGroupT.parquet';

-- name: vessel_use
select v.code, v.name, count(*) as efforts, min(e.effort_date) as first, max(e.effort_date) as last
from 'Data/Postgres/app/daily_effort.parquet' e join 'Data/Postgres/app/vessel.parquet' v on v.id = e.vessel_id
group by 1, 2 order by efforts desc limit 15;

-- name: vessels_single_use
select count(*) as vessels, count(*) filter (where n = 1) as used_once from (
  select vessel_id, count(*) as n from 'Data/Postgres/app/daily_effort.parquet' group by 1);

-- name: effort_length
-- Hours from start_time to end_time, where both are set and end is after start.
select count(*) as with_both, quantile_cont(h, [0.1, 0.5, 0.9]) as p10_p50_p90, max(h) as max_h from (
  select (epoch(end_time::time) - epoch(start_time::time)) / 3600.0 as h
  from 'Data/Postgres/app/daily_effort.parquet' where start_time is not null and end_time is not null)
where h > 0;

-- name: region_mix
select region, count(*) as efforts from 'Data/Postgres/app/daily_effort.parquet' group by 1 order by 2 desc;

-- name: geographic_extent
select 'sighting' as entity, min(lat), max(lat), min(lon), max(lon),
       count(*) filter (where lat < 0 or lon > 0) as outside_ne_pacific,
       count(*) filter (where lat between 5 and 75 and lon between -180 and -80) as in_ne_pacific
from 'Data/Postgres/app/sighting.parquet' where lat is not null
union all select 'sighting_end', min(end_lat), max(end_lat), min(end_lon), max(end_lon),
       count(*) filter (where end_lat < 0 or end_lon > 0 or end_lon < -180),
       count(*) filter (where end_lat between 5 and 75 and end_lon between -180 and -80)
from 'Data/Postgres/app/sighting.parquet' where end_lat is not null
union all select 'daily_condition', min(lat), max(lat), min(lon), max(lon),
       count(*) filter (where lat < 0 or lon > 0), count(*) filter (where lat between 5 and 75 and lon between -180 and -80)
from 'Data/Postgres/app/daily_condition.parquet' where lat is not null
union all select 'daily_event', min(lat), max(lat), min(lon), max(lon),
       count(*) filter (where lat < 0 or lon > 0), count(*) filter (where lat between 5 and 75 and lon between -180 and -80)
from 'Data/Postgres/app/daily_event.parquet' where lat is not null
union all select 'mnid_sighting', min(Dec_Lat), max(Dec_Lat), min(Dec_Long), max(Dec_Long),
       count(*) filter (where Dec_Lat < 0 or Dec_Long > 0), count(*) filter (where Dec_Lat between 5 and 75 and Dec_Long between -180 and -80)
from 'Data/MnID/mn_id_sightings.parquet' where Dec_Lat is not null;

-- name: sighting_value_outliers
select count(*) filter (where est_size_best > 1000) as size_over_1000,
       count(*) filter (where num_calves > est_size_best) as calves_over_size,
       count(*) filter (where depth_m > 11000) as depth_over_11km,
       count(*) filter (where bearing < 0 or bearing > 360) as bearing_out_of_range,
       count(*) filter (where range_m < 0) as negative_range
from 'Data/Postgres/app/sighting.parquet';

-- name: condition_value_outliers
select count(*) filter (where beaufort > 12) as beaufort_over_12,
       count(*) filter (where cloud_cover_pct > 100) as cloud_over_100,
       count(*) filter (where swell_ft < 0 or swell_ft > 50) as swell_out_of_range,
       count(*) filter (where visibility_nm > 50) as visibility_over_50
from 'Data/Postgres/app/daily_condition.parquet';

-- name: timeline_kinds
select kind, count(*) as n, count(*) filter (where daily_effort_id is null) as no_effort
from 'Data/Postgres/app/effort_timeline.parquet' group by 1;

-- name: event_codes_used
select e.code, c.name, count(*) as n from 'Data/Postgres/app/daily_event.parquet' e
left join 'Data/Postgres/app/event_code.parquet' c on c.id = e.event_code_id group by 1, 2 order by 3 desc limit 15;

-- name: track_status
select track_status, useable, count(*) as n, count(*) filter (where daily_effort_id is null) as no_effort,
       count(*) filter (where geom is null) as no_geometry
from 'Data/Postgres/app/track.parquet' group by 1, 2 order by 3 desc;

-- name: tracks_per_effort
select tracks, count(*) as efforts from (
  select daily_effort_id, count(*) as tracks from 'Data/Postgres/app/track.parquet'
  where daily_effort_id is not null group by 1) group by 1 order by 1;

-- name: efforts_with_track
select count(*) as efforts, count(*) filter (where t.daily_effort_id is not null) as with_track,
       count(*) filter (where t.daily_effort_id is not null and e.effort_date >= date '2013-01-01') as with_track_since_2013,
       count(*) filter (where e.effort_date >= date '2013-01-01') as efforts_since_2013
from 'Data/Postgres/app/daily_effort.parquet' e
left join (select distinct daily_effort_id from 'Data/Postgres/app/track.parquet') t on t.daily_effort_id = e.id;

-- name: track_size
select count(*) as tracks, sum(point_count) as total_points,
       quantile_cont(point_count, [0.5, 0.9, 0.99]) as p50_p90_p99_points, max(point_count) as max_points,
       quantile_cont(length_nm, [0.5, 0.9]) as p50_p90_nm, max(length_nm) as max_nm
from 'Data/Postgres/app/track.parquet' where point_count > 0;

-- name: track_point_spacing_and_speed
-- Seconds between GPS points and mean speed in knots, from point count, duration and length.
select quantile_cont(sec_per_point, [0.1, 0.5, 0.9]) as sec_per_point_p10_p50_p90,
       quantile_cont(knots, [0.1, 0.5, 0.9]) as knots_p10_p50_p90,
       quantile_cont(hours, [0.1, 0.5, 0.9]) as hours_p10_p50_p90
from (select epoch(end_time_utc - start_time_utc) / nullif(point_count - 1, 0) as sec_per_point,
             length_nm / nullif(epoch(end_time_utc - start_time_utc) / 3600.0, 0) as knots,
             epoch(end_time_utc - start_time_utc) / 3600.0 as hours
      from 'Data/Postgres/app/track.parquet' where point_count > 1);

-- name: track_points_by_year
select year(survey_date) as yr, count(*) as tracks, sum(point_count) as points
from 'Data/Postgres/app/track.parquet' group by 1 order by 1;

-- name: track_geometry_parts
-- Number of line parts per track: more than one part means the stored line already breaks at gaps.
select parts, count(*) as tracks from (
  select ST_NumGeometries(ST_GeomFromText(geom)) as parts from 'Data/Postgres/app/track.parquet' where geom is not null)
group by 1 order by 1 limit 20;

-- name: track_geometry_vertices
-- Vertices kept in the stored line against the raw point count: how much the line is simplified.
select quantile_cont(ratio, [0.1, 0.5, 0.9]) as kept_share_p10_p50_p90, sum(v) as total_vertices from (
  select ST_NPoints(ST_GeomFromText(geom)) as v, ST_NPoints(ST_GeomFromText(geom)) / point_count::double as ratio
  from 'Data/Postgres/app/track.parquet' where geom is not null and point_count > 0);

-- name: sample_links
select count(*) as samples, count(*) filter (where sighting_id is null) as no_sighting,
       count(*) filter (where sample_number is null) as no_number,
       count(distinct sample_number) as distinct_numbers
from 'Data/Postgres/app/sample.parquet';

-- name: identification_links
select count(*) as identifications,
       count(*) filter (where IndividualID is null) as no_individual,
       count(*) filter (where sighting_id is null) as no_sighting,
       count(*) filter (where "CRC ID" is null) as no_catalog_id,
       count(distinct sighting_id) as sightings_with_ids
from 'Data/Postgres/dbo/IdentificationT.parquet';

-- name: identifications_by_species
select sp.common_name, count(*) as identifications, count(distinct i.IndividualID) as individuals
from 'Data/Postgres/dbo/IdentificationT.parquet' i left join 'Data/Postgres/app/species.parquet' sp on sp.id = i.species_id
group by 1 order by 2 desc limit 12;

-- name: identification_record_type
select "Record Type", count(*) as n from 'Data/Postgres/dbo/IdentificationT.parquet' group by 1 order by 2 desc;

-- name: individuals_by_species
select sp.common_name, count(*) as individuals, min("CRC ID") as min_id, max("CRC ID") as max_id
from 'Data/Postgres/dbo/IndividualT.parquet' i left join 'Data/Postgres/app/species.parquet' sp on sp.id = i.species_id
group by 1 order by 2 desc limit 12;

-- name: sightings_per_individual
select quantile_cont(n, [0.5, 0.9, 0.99]) as p50_p90_p99, max(n) as max_n, count(*) as individuals from (
  select IndividualID, count(*) as n from 'Data/Postgres/dbo/IdentificationT.parquet' where IndividualID is not null group by 1);

-- name: mnid_sources
select Record_Source, count(*) as n from 'Data/MnID/mn_id_sightings.parquet' group by 1 order by 2 desc limit 15;

-- name: mnid_sharing_status
select coalesce(upper(Sharing_Status), '(blank)') as status, count(*) as n from 'Data/MnID/mn_id_sightings.parquet' group by 1 order by 2 desc;

-- name: mnid_records_per_individual
select quantile_cont(n, [0.5, 0.9, 0.99]) as p50_p90_p99, max(n) as max_n, count(*) as individuals from (
  select CRC_ID, count(*) as n from 'Data/MnID/mn_id_sightings.parquet' where CRC_ID is not null group by 1);

-- name: mnid_ids_not_in_summary
select count(distinct s.CRC_ID) as sighting_ids, count(distinct s.CRC_ID) filter (where m.CRC_ID is null) as not_in_summary
from 'Data/MnID/mn_id_sightings.parquet' s left join 'Data/MnID/mn_id_summary.parquet' m on m.CRC_ID = s.CRC_ID
where s.CRC_ID is not null;

-- name: mnid_alias_shape
select count(*) as aliases,
       count(*) filter (where Correct is null) as no_target,
       count(*) filter (where Correct = 0) as target_zero,
       count(*) filter (where Correct in (select "Old_#" from 'Data/MnID/crc_mn_alias_list.parquet')) as target_also_retired,
       count(distinct "Old_#") as distinct_old
from 'Data/MnID/crc_mn_alias_list.parquet';

-- name: mnid_alias_old_still_used
-- Retired IDs that still appear as CRC_ID on sighting records.
select count(distinct a."Old_#") as old_ids_still_on_records
from 'Data/MnID/crc_mn_alias_list.parquet' a join 'Data/MnID/mn_id_sightings.parquet' s on s.CRC_ID = a."Old_#";

-- name: mnid_retired_shape
select count(*) as rows, count(RCRCID2) as with_second, count(RCRCID3) as with_third, count(RCRCID4) as with_fourth
from 'Data/MnID/retired_crc_ids.parquet';

-- name: mnid_other_catalog_ids
select count(SPLASH_ID) as splash, count(DFO_ID) as dfo, count(HappyWhale_ID) as happywhale, count(WGRP) as wgrp,
       count(UABCS_ID) as uabcs, count(UNAM_ID) as unam, count(Other_ID) as other, count(*) as individuals
from 'Data/MnID/mn_id_summary.parquet';

-- name: mnid_dead
select count(*) filter (where "Dead?") as dead_individuals from 'Data/MnID/mn_id_summary.parquet';

-- name: mnid_to_crc_sightings
-- MnID records from CRC that match a CRC sighting by date and sighting number (the likely join).
select count(*) as crc_records,
       count(*) filter (where exists (
         select 1 from 'Data/Postgres/app/sighting.parquet' s
         where s.sighting_date = m.Date::date and s.sighting_number = m.Sighting)) as match_date_and_number
from 'Data/MnID/mn_id_sightings.parquet' m where m.Record_Source = 'CRC';

-- name: mnid_vs_identification_humpback
-- Humpback IDs in V1's IdentificationT against MnID's catalog numbers.
select count(distinct i."CRC ID") as v1_humpback_ids,
       count(distinct i."CRC ID") filter (where m.CRC_ID is not null) as also_in_mnid
from 'Data/Postgres/dbo/IdentificationT.parquet' i
join 'Data/Postgres/app/species.parquet' sp on sp.id = i.species_id and sp.code = 'Mn'
left join 'Data/MnID/mn_id_summary.parquet' m on m.CRC_ID = i."CRC ID";

-- name: mnid_samples_links
select count(*) as samples, count(CRC_ID) as with_individual, count(distinct Record_Source) as sources
from 'Data/MnID/mn_id_samples.parquet';

-- name: mnid_location_codes
select count(*) as records, count(Loc_Code) as with_code, count(distinct Loc_Code) as codes
from 'Data/MnID/mn_id_sightings.parquet';

-- name: species_categories
select category, count(*) as species from 'Data/Postgres/app/species.parquet' group by 1 order by 2 desc;

-- name: individual_duplicates
-- Catalog numbers that appear on more than one individual of the same species, and placeholder zeros.
select count(*) filter (where n > 1) as duplicated_numbers, sum(n) filter (where n > 1) as rows_involved,
       (select count(*) from 'Data/Postgres/dbo/IndividualT.parquet' where "CRC ID" = 0) as id_zero,
       (select count(*) from 'Data/Postgres/dbo/IndividualT.parquet' where "CRC ID" is null) as id_null
from (select species_id, "CRC ID", count(*) as n from 'Data/Postgres/dbo/IndividualT.parquet'
      where "CRC ID" is not null and "CRC ID" <> 0 group by 1, 2);

-- name: identification_without_individual
select coalesce("Record Type", '(blank)') as record_type, count(*) as n
from 'Data/Postgres/dbo/IdentificationT.parquet' where IndividualID is null group by 1 order by 2 desc;

-- name: recent_years_by_group
-- Why 2025 and 2026 are small: which research groups have loaded data so far.
select year(sighting_date) as yr, research_group, count(*) as n from 'Data/Postgres/app/sighting.parquet'
where sighting_date >= date '2024-01-01' group by 1, 2 qualify row_number() over (partition by yr order by n desc) <= 4 order by 1, 3 desc;

-- name: sighting_time_precision
-- Share of sighting times that fall on a whole minute, and placeholder noon times.
select count(*) filter (where sighting_time like '%:00') as whole_minute,
       count(*) filter (where sighting_time = '12:00:00') as noon,
       count(sighting_time) as with_time
from 'Data/Postgres/app/sighting.parquet';

-- name: sightings_with_end_position
select count(*) filter (where end_lat is not null) as with_end, count(*) as total from 'Data/Postgres/app/sighting.parquet';

-- name: identifications_per_sighting
select quantile_cont(n, [0.5, 0.9, 0.99]) as p50_p90_p99, max(n) as max_n from (
  select sighting_id, count(*) as n from 'Data/Postgres/dbo/IdentificationT.parquet' where sighting_id is not null group by 1);

-- name: conditions_and_events_per_effort
select 'condition' as kind, quantile_cont(n, [0.5, 0.9]) as p50_p90, max(n) as max_n from (
  select daily_effort_id, count(*) as n from 'Data/Postgres/app/daily_condition.parquet' where daily_effort_id is not null group by 1)
union all select 'event', quantile_cont(n, [0.5, 0.9]), max(n) from (
  select daily_effort_id, count(*) as n from 'Data/Postgres/app/daily_event.parquet' where daily_effort_id is not null group by 1);

-- name: track_duplicate_object_keys
select count(*) as keys_used_twice from (
  select object_key from 'Data/Postgres/app/track.parquet' group by 1 having count(*) > 1);

-- name: track_parquet_size_estimate
-- Size on disk of every GPS point in Parquet (zstd), using invented points at V1's volume:
-- 10,397,499 points in 1,552 tracks, one GPS point every 15 s, a random walk at about 7 knots.
-- Run scratch/profile/track_size.py; it writes scratch/profile/points.parquet and prints the bytes.
select 10397499 as points, 1552 as tracks;

-- name: sightings_by_hour
select hour(sighting_time::time) as hour, count(*) as n, round(100.0 * count(*) / sum(count(*)) over (), 1) as pct
from 'Data/Postgres/app/sighting.parquet' where sighting_time is not null group by 1 order by 1;

-- name: sub_area_extent
-- Where surveys happen: the busiest sub-areas with the spread of their sighting positions.
select e.sub_area, count(distinct e.id) as efforts, count(s.id) as sightings,
       round(quantile_cont(s.lat, 0.1), 2) as lat_p10, round(quantile_cont(s.lat, 0.9), 2) as lat_p90,
       round(quantile_cont(s.lon, 0.1), 2) as lon_p10, round(quantile_cont(s.lon, 0.9), 2) as lon_p90
from 'Data/Postgres/app/daily_effort.parquet' e join 'Data/Postgres/app/sighting.parquet' s on s.daily_effort_id = e.id
where s.lat is not null group by 1 order by efforts desc limit 15;

-- name: species_by_region
select e.region, sp.common_name, count(*) as n
from 'Data/Postgres/app/sighting.parquet' s join 'Data/Postgres/app/daily_effort.parquet' e on e.id = s.daily_effort_id
join 'Data/Postgres/app/species.parquet' sp on sp.id = s.species_id
where e.region in ('US West Coast', 'British Columbia', 'Mexico')
group by 1, 2
qualify row_number() over (partition by e.region order by count(*) desc) <= 5
order by 1, 3 desc;

-- name: efforts_by_year_with_track
select year(e.effort_date) as yr, count(*) as efforts, count(t.daily_effort_id) as with_track
from 'Data/Postgres/app/daily_effort.parquet' e
left join (select distinct daily_effort_id from 'Data/Postgres/app/track.parquet') t on t.daily_effort_id = e.id
where e.effort_date >= date '2013-01-01' group by 1 order by 1;

-- name: crc_share_of_tracked_efforts
select e.research_group, count(*) as efforts_with_track from 'Data/Postgres/app/daily_effort.parquet' e
join (select distinct daily_effort_id from 'Data/Postgres/app/track.parquet') t on t.daily_effort_id = e.id
group by 1 order by 2 desc limit 5;
