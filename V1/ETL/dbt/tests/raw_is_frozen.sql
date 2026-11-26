-- Every table of DB167's in raw is frozen: its trigger refuses any change,
-- so raw stays exactly what was imported. The build's own inputs in raw (the
-- species, event code and vessel lists, and the GPS lines) are written to on
-- purpose, and are left out.
select c.relname as table_name
from pg_class c
where c.relnamespace = 'raw'::regnamespace and c.relkind = 'r'
  and c.relname not in ('species', 'event_code_name', 'vessel_list', 'track_geometry')
  and not exists (select 1 from pg_trigger t
                  where t.tgrelid = c.oid and not t.tgisinternal
                    and t.tgfoid = 'raw.frozen'::regproc)
