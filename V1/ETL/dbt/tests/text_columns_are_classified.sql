-- Every text column of a table that goes on to dbo is in seeds/column_kinds.csv
-- as a choice, free text or an identifier. A column DB167 gains is treated as
-- free text (trimmed, nothing more) until someone classifies it; this warns.
{{ config(severity='warn') }}
select c.table_name, c.column_name
from information_schema.columns c
where c.table_schema = 'raw' and c.data_type in ('text', 'character varying')
  and c.table_name in ({% for t in cleaned_tables() %}'{{ t }}'{{ ", " if not loop.last }}{% endfor %})
  and not exists (select 1 from {{ ref('column_kinds') }} k
                  where k.table_name = c.table_name and k.column_name = c.column_name)
