{#
  The newest value of every field an edit set, one row per record:
  {"column": value, ...} in `changes`. Edits are app.audit_log entries that
  change fields -- update, associate, dissociate, upload, and create, whose
  "changes" hold the whole new row.

  Two kinds of entry are left out, because together they cancel: an entry the
  old Restore reversed (restored_by is set), and the restore entry itself.
  Undo today deletes the entry it reverses, so those pairs are the only
  reversed changes the log still holds.
#}
with entries as (
    select id, action, target_table, target_pk, changes
    from {{ source('app', 'audit_log') }}
    where action in ('update', 'associate', 'dissociate', 'upload', 'create')
      and restored_by is null
      and id <= {{ audit_watermark() }}
      and changes is not null
),
fields as (
    select distinct on (e.target_table, e.target_pk, f.key)
           e.target_table, e.target_pk, f.key as column_name, f.value -> 'new' as new_value
    from entries e, jsonb_each(e.changes) f
    order by e.target_table, e.target_pk, f.key, e.id desc
)
select target_table, target_pk, jsonb_object_agg(column_name, new_value) as changes
from fields
group by target_table, target_pk
