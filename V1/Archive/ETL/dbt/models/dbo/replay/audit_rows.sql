{#
  Records the website created or deleted, and whether each exists now:
  state is 'created' or 'deleted', from the newest create or delete entry.

  A delete's snapshot holds the record and every row that depended on it,
  keyed by table ({"SightingT": [...], "SampleT": [...], "__order__": [...]}),
  because audit.delete() removes them all. Each of those rows counts as
  deleted, from its own table. Primary keys are read from the raw schema,
  whose tables and keys are the dbo tables'.

  As in audit_changes, an entry the old Restore reversed, and the restore
  entry, are left out.
#}
with entries as (
    select id, action, target_table, target_pk, snapshot
    from {{ source('app', 'audit_log') }}
    where action in ('create', 'delete')
      and restored_by is null
      and id <= {{ audit_watermark() }}
),
primary_keys as (
    select c.relname as table_name, a.attname as key_column
    from pg_index i
    join pg_class c on c.oid = i.indrelid
    join pg_attribute a on a.attrelid = i.indrelid and a.attnum = any(i.indkey)
    where c.relnamespace = 'raw'::regnamespace and i.indisprimary
),
events as (
    select id, target_table, target_pk, 'created' as state
    from entries where action = 'create'
    union all
    select e.id, t.key, r ->> k.key_column, 'deleted'
    from entries e
    cross join lateral jsonb_each(e.snapshot) t
    cross join lateral jsonb_array_elements(case when jsonb_typeof(t.value) = 'array' then t.value else '[]'::jsonb end) r
    join primary_keys k on k.table_name = t.key
    where e.action = 'delete'
)
select distinct on (target_table, target_pk) target_table, target_pk, state
from events
order by target_table, target_pk, id desc
