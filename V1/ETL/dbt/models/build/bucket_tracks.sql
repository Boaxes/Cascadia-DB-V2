-- GPS files in the bucket (app.track_geometry) that no track record names: no
-- track record there is once the audit log is applied, DB167's (less those
-- the website deleted) or one the website created (unless it deleted it
-- again), by the file name it has after the website's edits. Each gets a
-- TrackT record, with its date and vessel read from the file's name:
-- 20190703-KOH-tblt.csv is vessel KOH on 3 July 2019.
--
-- Its TrackID is kept with the file (app.track_geometry.track_id), so it never
-- moves. A file met for the first time is numbered on from the highest TrackID
-- anything has, in file-name order, and the swap saves the number.
with tracks as (
    -- A track dbo leaves out (it names no vessel) does not name its file.
    select t."TrackID"::text as track_id, t."TrackFileName" as file_name from {{ source('raw', 'TrackT') }} t
    where not {{ track_names_no_vessel('t') }}
    union all
    select target_pk, null from {{ ref('edit_rows') }} where target_table = 'TrackT' and state = 'created'
),
named as (
    -- As dbo.TrackT's file_name: the website's file_name, else its
    -- TrackFileName, else DB167's.
    select lower(btrim(case when e.changes ? 'file_name' then e.changes ->> 'file_name'
                            when e.changes ? 'TrackFileName' then e.changes ->> 'TrackFileName'
                            else t.file_name end)) as name
    from tracks t
    left join {{ ref('edits') }} e on e.target_table = 'TrackT' and e.target_pk = t.track_id
    where not exists (select 1 from {{ ref('edit_rows') }} d
                      where d.target_table = 'TrackT' and d.state = 'deleted' and d.target_pk = t.track_id)
),
highest as (
    select greatest((select max("TrackID") from {{ source('raw', 'TrackT') }}),
                    (select max(track_id) from {{ source('app', 'track_geometry') }}),
                    (select max(target_pk::integer) from {{ source('app', 'audit_log') }}
                     where target_table = 'TrackT' and action = 'create')) as n
),
files as (
    select g.* from {{ source('app', 'track_geometry') }} g
    where not exists (select 1 from named n where n.name = lower(btrim(g.object_key)))
)
select coalesce(g.track_id,
                (select n from highest) + row_number() over (partition by g.track_id is null
                                                             order by g.object_key collate "C"))::integer as "TrackID",
       g.object_key as file_name,
       case when g.object_key ~ '^[0-9]{8}' then to_date(left(g.object_key, 8), 'YYYYMMDD') end as survey_date,
       upper(substring(g.object_key from '^[0-9]{8}-([A-Za-z0-9]+)')) as vessel,
       g.track_id is null as is_new
from files g
