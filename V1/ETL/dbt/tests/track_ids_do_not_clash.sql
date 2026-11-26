-- A TrackID the website gave a track it created, or the build gave a file in
-- the bucket, that DB167 has since used for a track of its own. The two would
-- be taken for one record, so the build stops until it is sorted out.
select t."TrackID", t."TrackFileName" as db167_file, c.file_name as other_file
from {{ source('raw', 'TrackT') }} t
join (
    select target_pk::integer as track_id, changes -> 'TrackFileName' ->> 'new' as file_name
    from {{ source('app', 'audit_log') }}
    where target_table = 'TrackT' and action = 'create' and restored_by is null
    union all
    select track_id, object_key from {{ source('app', 'track_geometry') }} where track_id is not null
) c on c.track_id = t."TrackID"
where lower(btrim(t."TrackFileName")) is distinct from lower(btrim(c.file_name))
