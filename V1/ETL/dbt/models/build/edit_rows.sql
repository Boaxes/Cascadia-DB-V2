-- Records the website created or deleted, and whether each exists now: state
-- is 'created' or 'deleted', from the newest create or delete entry
-- (models/build/audit_entries.sql). A delete counts for every row its
-- snapshot keeps, each in its own table.
select distinct on (target_table, target_pk) target_table, target_pk,
       case action when 'create' then 'created' else 'deleted' end as state
from {{ ref('audit_entries') }}
where action in ('create', 'delete') and target_pk is not null
order by target_table, target_pk, id desc
