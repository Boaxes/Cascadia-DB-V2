-- What DB167 already holds is replayed no more (db167_state, db167_fields;
-- macros/db167_state.sql; models/build/audit_entries.sql): not a create or a
-- delete it holds, and not a field of an update it holds. Replaying them would
-- write the website's copy over what DB167 holds, or over what DB167 has
-- changed since.
select a.id, a.action, a.target_table, null as field
from {{ source('app', 'audit_log') }} a
join {{ ref('audit_entries') }} e on e.id = a.id
where a.db167_state = 'applied' and a.action in ('create', 'delete')
union all
select a.id, a.action, a.target_table, f.key
from {{ source('app', 'audit_log') }} a
join {{ ref('audit_entries') }} e on e.id = a.id
cross join lateral jsonb_each(coalesce(e.changes, '{}'::jsonb)) f
where a.db167_fields ->> f.key = 'applied'
