-- TrackT: GPS track files, one row per file, with the website's edits. Its
-- Primary Key is DB167's TrackID, which has never changed.
--
-- A file in the bucket that no track record names gets one
-- (models/build/bucket_tracks.sql). Comments lose the HTML tags DB167 stores
-- in them.
--
-- A track whose VesselID names a vessel VesselT no longer has, and which has no
-- typed Vessel and no EffortID, has nothing that says whose it is, so it is left out.
-- A track whose EffortID names an effort DB167 removed as a copy of another
-- (seeds/removed_efforts.csv) has its EffortID changed to the effort it kept.
--
--   daily_effort_id  FK to DailyEffortT.id: the effort a person matched the
--                    track to on the website, else the effort DB167's EffortID
--                    names in this copy of DB167; NULL (unmatched) if that
--                    effort is not in this copy
--   vessel_id        FK to VesselListT, by the typed Vessel, else by VesselID
--   geom, length_nm, point_count  the file's line, from app.track_geometry
--   track_status     available (matched, file has points), blank (matched,
--                    file has no points yet), unassociated (stored, not
--                    matched) or unresolved (neither)
--   file_name        the file's name in the bucket: TrackFileName, unless the
--                    website set it
--   StartTime, EndTime  DB167 keeps them in Pacific local time; dbo keeps UTC,
--                    converted here (macros/track_times.sql). The website's own
--                    values are UTC already and are replayed as they are.
--
-- ResearchGroupID, TrackCompleteCodeID and SourceID are copied from DB167, or
-- set on the website; one that names no record is left NULL, an orphan.
{%- set overrides = {
    'Comments': "case when c0.\"Comments\" ~ '<[^>]*>' then " ~ trimmed("regexp_replace(c0.\"Comments\", '<[^>]*>', ' ', 'g')") ~ " else c0.\"Comments\" end",
    'EffortID': kept_effort('c0."EffortID"'),
    'StartTime': 'app.track_time_utc(c0."StartTime", ' ~ geometry_time('first_time') ~ ')',
    'EndTime': 'app.track_time_utc(c0."EndTime", ' ~ geometry_time('last_time') ~ ')',
} %}
{%- set from_bucket = {
    'TrackID': 'b."TrackID"', 'SurveyDate': 'b.survey_date', 'TrackFileName': 'b.file_name',
    'TrackFileType': "'csv'", 'Useable': 'true', 'Vessel': 'b.vessel',
} %}
with {{ cleaned_ctes('TrackT', overrides) }},
rows as (
    select {{ column_list('TrackT', 'c') }} from c
    where not {{ track_names_no_vessel('c') }}
    union all
    select
    {%- for col in raw_columns('TrackT') %}
        ({{ from_bucket.get(col.name, 'null') }})::{{ col.data_type }}{{ "," if not loop.last }}
    {%- endfor %}
    from {{ ref('bucket_tracks') }} b
),
r as (
    {{ replay_rows('rows', 'TrackT', 'TrackID') }}
),
s as (
    select {{ replayed_columns('TrackT', 'r') }}, r.__edits,
           {{ edited('file_name', 'btrim(' ~ edited('TrackFileName', 'r."TrackFileName"', 'text', 'r.__edits') ~ ')', 'text', 'r.__edits') }} as file_name
    from r
),
matched as (
    select s.*,
           {{ edited('daily_effort_id', legacy_id(ref('keyed_DailyEffortT'), 'DailyEffortID', 's."EffortID"'), 'bigint', 's.__edits') }} as __effort
    from s
),
-- An effort DB167 has since removed, or the website deleted, leaves the track
-- unmatched, waiting to be matched again.
linked as (
    select m.*, (select v.id from (select m.__effort as id) v
                 where {{ exists_after_replay('DailyEffortT', 'v.id') }}) as daily_effort_id
    from matched m
)
select {{ column_list('TrackT', 's', {
           'ResearchGroupID': checked_reference('s."ResearchGroupID"', 'ResearchGroupT'),
           'TrackCompleteCodeID': checked_reference('s."TrackCompleteCodeID"', 'TrackCompleteCodeT'),
           'SourceID': checked_reference('s."SourceID"', 'SourceT'),
       }) }},
       s.daily_effort_id,
       coalesce(vk.vessel_id, (select min(v.vessel_id) from {{ ref('vessels') }} v
                               where v.legacy_vessel_id = s."VesselID"))::integer as vessel_id,
       g.geom::geometry(MultiLineString, 4326) as geom,
       g.length_nm::numeric(12,3) as length_nm,
       g.point_count::integer as point_count,
       case when s.daily_effort_id is not null and coalesce(g.point_count, 0) > 0 then 'available'
            when s.daily_effort_id is not null then 'blank'
            when g.object_key is not null then 'unassociated'
            else 'unresolved' end as track_status,
       s.file_name
from linked s
left join {{ source('app', 'track_geometry') }} g on lower(g.object_key) = lower(s.file_name)
left join {{ ref('vessel_keys') }} vk on vk.key = {{ build_fn() }}.key_text(s."Vessel")
