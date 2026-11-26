-- Every value of every choice column (seeds/column_kinds.csv) of the tables
-- that go on to dbo, with how many records hold it, as DB167 has it.
--
--   unit  what one set of merges covers: the column, or for research group,
--         vessel and species, every column that holds one, across tables, so
--         a value is spelled the same wherever it appears.
{%- set rows = [] -%}
{%- set kinds_seed = ref('column_kinds') -%}
{%- if execute -%}
    {%- set rows = run_query("select table_name, column_name, coalesce(nullif(vocabulary, ''), table_name || '.' || column_name)
                              from " ~ kinds_seed ~ " where kind = 'choice' order by 1, 2") -%}
{%- endif -%}
{%- set parts = [] -%}
{%- for r in rows -%}
    {%- if r[1] in raw_column_names(r[0]) -%}
        {%- do parts.append((r[0], r[1], r[2])) -%}
    {%- endif -%}
{%- endfor %}

{% for table_name, column_name, unit in parts %}
select '{{ table_name }}'::text as table_name, '{{ column_name }}'::text as column_name, '{{ unit }}'::text as unit,
       {{ adapter.quote(column_name) }}::text as value, count(*)::integer as records
from {{ source('raw', table_name) }}
where {{ trimmed(adapter.quote(column_name)) }} is not null
group by {{ adapter.quote(column_name) }}
{{ "union all" if not loop.last }}
{%- endfor %}
{%- if not parts %}
select null::text as table_name, null::text as column_name, null::text as unit, null::text as value, 0 as records
where false
{%- endif %}
