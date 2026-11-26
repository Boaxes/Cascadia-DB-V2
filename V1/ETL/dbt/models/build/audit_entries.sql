-- The app.audit_log entries this build replays, one row per record an entry
-- is about, with that record's Primary Key in this build. The log up to the
-- build's watermark (macros/replay.sql, audit_watermark), less what the old
-- Restore reversed: an entry with restored_by set, and the restore entry
-- itself, cancel out.
--
-- A delete is about every row its snapshot keeps ({"SightingT": [...],
-- "SampleT": [...]}), because the website deletes a record and everything
-- that depends on it together; each row is found by its own table's Primary
-- Key (macros/replay.sql, primary_keys).
--
-- In the 8 tables with a hashed Primary Key, a record's id changes when DB167
-- changes one of its key columns. An entry whose id this build does not have
-- finds its record by the Legacy ID the entry keeps (legacy_pk, or the
-- snapshot row's own), if this build has a record with it; otherwise it keeps
-- the id it has, and waits unused.
--
-- What DB167 already holds is not replayed (db167_state, db167_fields;
-- macros/db167_state.sql): replaying it would only write DB167's own value
-- again, or overwrite what DB167 has changed since. A create or delete DB167
-- holds is left out whole. Of an update, the fields DB167 holds are taken
-- out, one by one: what is left is what DB167 does not hold yet, and the
-- values it has no column for (a sighting's depth_m), which exist only here.
-- daily_effort_id and file_name go with the EffortID and TrackFileName they
-- are worked out from. An entry about a track DB167 has no row for (every
-- track the website made) has no map of fields: nothing of it is held by
-- DB167, so those two stay.
{%- set hashed = hashed_tables() %}
with entries as (
    select a.id, a.action, a.target_table, a.target_pk, a.legacy_pk, a.snapshot,
           case when a.changes is null then null
                else coalesce((select jsonb_object_agg(f.key, f.value)
                               from jsonb_each(a.changes) f
                               where coalesce(a.db167_fields ->> f.key, '') <> 'applied'
                                 and not (f.key = 'daily_effort_id' and coalesce(a.db167_fields ->> 'EffortID', '') = 'applied')
                                 and not (f.key = 'file_name' and coalesce(a.db167_fields ->> 'TrackFileName', '') = 'applied')),
                              '{}'::jsonb) end as changes
    from {{ source('app', 'audit_log') }} a
    where a.restored_by is null
      and a.action <> 'restore'
      and a.id <= {{ audit_watermark() }}
      and not (a.db167_state = 'applied' and a.action in ('create', 'delete'))
),
keys (table_name, key_column, legacy_column) as (
    values
    {%- for t, k in primary_keys().items() %}
        ('{{ t }}', '{{ k }}', {{ "'" ~ hashed[t] ~ "'" if t in hashed else 'null' }}){{ "," if not loop.last }}
    {%- endfor %}
),
records as (
    select id, action, target_table, target_pk, legacy_pk, changes
    from entries where action <> 'delete'
    union all
    select e.id, e.action, t.key, r ->> k.key_column,
           coalesce(r ->> k.legacy_column, case when t.key = e.target_table then e.legacy_pk end), null
    from entries e
    cross join lateral jsonb_each(e.snapshot) t
    cross join lateral jsonb_array_elements(case when jsonb_typeof(t.value) = 'array' then t.value else '[]'::jsonb end) r
    join keys k on k.table_name = t.key
    where e.action = 'delete'
),
ids as (
    {%- for t, legacy in hashed.items() %}
    select '{{ t }}'::text as table_name, id::text as id, {{ adapter.quote(legacy) }}::text as legacy
    from {{ ref('keyed_' ~ t) }}
    {{ "union all" if not loop.last }}
    {%- endfor %}
)
select r.id, r.action, r.target_table,
       coalesce(by_id.id, by_legacy.id, r.target_pk) as target_pk,
       r.target_pk as logged_pk, r.changes
from records r
left join (select distinct table_name, id from ids) by_id
       on by_id.table_name = r.target_table and by_id.id = r.target_pk
left join ids by_legacy
       on by_legacy.table_name = r.target_table and by_legacy.legacy = r.legacy_pk and by_id.id is null
