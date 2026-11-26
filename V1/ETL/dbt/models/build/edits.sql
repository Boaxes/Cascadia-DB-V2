-- The newest value of every field the website set, one row per record:
-- {"column": value, ...} in `changes`. From the audit log entries that change
-- fields (models/build/audit_entries.sql): update, associate, dissociate,
-- upload, edit_file, and create, whose changes hold the whole new row.
with fields as (
    select distinct on (e.target_table, e.target_pk, f.key)
           e.target_table, e.target_pk, f.key as column_name, f.value -> 'new' as new_value
    from {{ ref('audit_entries') }} e, jsonb_each(e.changes) f
    where e.action in ('update', 'associate', 'dissociate', 'upload', 'edit_file', 'create')
      and e.changes is not null
    order by e.target_table, e.target_pk, f.key, e.id desc
)
select target_table, target_pk, jsonb_object_agg(column_name, new_value) as changes
from fields
group by target_table, target_pk
