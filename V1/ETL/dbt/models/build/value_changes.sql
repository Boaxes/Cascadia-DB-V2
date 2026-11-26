-- Every value the build changes, one row per table, column and original
-- spelling, with how many records hold it: the spelling rule's merges
-- (models/build/spelling_map.sql), spaces trimmed from free text and
-- identifiers, and empty text made NULL. The Data Pipeline page lists these on
-- each column.
--
--   kind  capitals, spaces, typo, synonym, corrected (merges), trim or empty
{%- set tables = cleaned_tables() %}
with merges as (
    select v.table_name, v.column_name, m.kind, v.value as from_value, m.to_value, v.records
    from {{ ref('spelling_values') }} v
    join {{ ref('spelling_map') }} m on m.unit = v.unit and m.from_value = v.value
),
blanks as (
    {%- set parts = [] %}
    {%- for t in tables %}
        {%- set k = text_kinds(t) %}
        {%- for c in raw_columns(t) if is_text(c) %}
            {%- do parts.append((t, c.name, k.get(c.name, ('free', ''))[0])) %}
        {%- endfor %}
    {%- endfor %}
    {%- for t, col, kind in parts %}
    select '{{ t }}'::text as table_name, '{{ col }}'::text as column_name,
           count(*) filter (where {{ trimmed(adapter.quote(col)) }} is null)::integer as empty,
           {%- if kind == 'choice' %}
           0 as trim
           {%- else %}
           count(*) filter (where {{ trimmed(adapter.quote(col)) }} <> {{ adapter.quote(col) }})::integer as trim
           {%- endif %}
    from {{ source('raw', t) }} where {{ adapter.quote(col) }} is not null
    {{ "union all" if not loop.last }}
    {%- endfor %}
)
select table_name, column_name, kind, from_value, to_value, records from merges
union all
select table_name, column_name, 'empty', null, null, empty from blanks where empty > 0
union all
select table_name, column_name, 'trim', null, null, trim from blanks where trim > 0
