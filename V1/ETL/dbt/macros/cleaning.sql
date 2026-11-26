{#
  How every text column of a dbo table is cleaned, read from
  seeds/column_kinds.csv:

    choice  a value chosen from a set (survey type, behaviour, vessel): the
            spelling rule's merges (models/build/spelling_map.sql), then
            empty text -> NULL.
    free    free text (comments, notes, lists of people), and
    id      identifiers (Field IDs, frame numbers, file names): spaces at the
            start and end removed, empty text -> NULL. Capitals never change.

  A text column the seed does not list is treated as free text, so a column
  DB167 gains later is trimmed and nothing more until someone classifies it.
  Columns that are not text pass through.

  In a model:

      with t as (select * from {{ source('raw', 'SightingT') }})
      select {{ cleaned_columns('SightingT') }}
      from t {{ cleaned_joins('SightingT') }}
#}

{# Every DB167 table that goes on to dbo, cleaned. #}
{% macro cleaned_tables() %}
    {{ return(['DailyConditionT', 'DailyEffortT', 'DailyEventT', 'EventCodeT', 'IdentificationT', 'IndividualT',
               'OtherSpeciesT', 'ResearchGroupT', 'SampleT', 'SightingEventT', 'SightingT', 'SourceT', 'SpeciesT',
               'TagSummaryT', 'TrackCompleteCodeT', 'TrackT']) }}
{% endmacro %}


{% macro raw_columns(table_name) %}
    {%- if execute -%}
        {{ return(adapter.get_columns_in_relation(source('raw', table_name))) }}
    {%- else -%}
        {{ return([]) }}
    {%- endif -%}
{% endmacro %}


{% macro raw_column_names(table_name) %}
    {%- set names = [] -%}
    {%- for c in raw_columns(table_name) -%}{%- do names.append(c.name) -%}{%- endfor -%}
    {{ return(names) }}
{% endmacro %}


{# {column: (kind, unit)} for one table: unit is what the spelling map is keyed by. #}
{% macro text_kinds(table_name) %}
    {%- set out = {} -%}
    {#- ref() outside the if, so dbt sees at parse time that the model reads the seed. -#}
    {%- set kinds_seed = ref('column_kinds') -%}
    {%- if execute -%}
        {%- set rows = run_query("select column_name, kind, coalesce(nullif(vocabulary, ''), table_name || '.' || column_name) from "
                                 ~ kinds_seed ~ " where table_name = '" ~ table_name ~ "'") -%}
        {%- for r in rows -%}{%- do out.update({r[0]: (r[1], r[2])}) -%}{%- endfor -%}
    {%- endif -%}
    {{ return(out) }}
{% endmacro %}


{% macro is_text(column) -%}
    {{ return(column.data_type in ('text', 'character varying')) }}
{%- endmacro %}


{#- Whitespace at either end, as Python's str.strip() sees it. -#}
{% macro trimmed(expression) -%}
    nullif(btrim({{ expression }}, E' \t\r\n\f\v '), '')
{%- endmacro %}


{% macro cleaned_columns(table_name, relation='t') %}
    {%- set kinds = text_kinds(table_name) -%}
    {%- for c in raw_columns(table_name) %}
        {%- set q = relation ~ '.' ~ adapter.quote(c.name) -%}
        {%- if is_text(c) and kinds.get(c.name, ('free', ''))[0] == 'choice' %}
        case when {{ trimmed(q) }} is null then null
             else coalesce(spell_{{ loop.index }}.to_value, {{ q }}) end as {{ adapter.quote(c.name) }}
        {%- elif is_text(c) %}
        {{ trimmed(q) }} as {{ adapter.quote(c.name) }}
        {%- else %}
        {{ q }} as {{ adapter.quote(c.name) }}
        {%- endif -%}
        {{ "," if not loop.last }}
    {%- endfor %}
{% endmacro %}


{% macro cleaned_joins(table_name, relation='t') %}
    {%- set kinds = text_kinds(table_name) -%}
    {%- set spelling_map = ref('spelling_map') -%}
    {%- for c in raw_columns(table_name) %}
        {%- if is_text(c) and kinds.get(c.name, ('free', ''))[0] == 'choice' %}
    left join {{ spelling_map }} spell_{{ loop.index }}
           on spell_{{ loop.index }}.unit = '{{ kinds[c.name][1] }}'
          and spell_{{ loop.index }}.from_value = {{ relation }}.{{ adapter.quote(c.name) }}
        {%- endif %}
    {%- endfor %}
{% endmacro %}


{#
  The key the spelling rule groups a value by (models/build/spelling_map.sql):
  trimmed, runs of spaces made one, in lower case. Group Type is also read
  with '+' and 'x' unspaced, so 'pair + single' is 'pair+single'.
#}
{% macro spelling_key(unit, value) -%}
    {%- set fn = build_fn() -%}
    case when {{ unit }} = 'SightingT.Group Type'
         then regexp_replace(regexp_replace({{ fn }}.key_text({{ value }}), '\s*\+\s*', '+', 'g'),
                             '(?<=\w)\s*x\s*(?=\d)', 'x', 'g')
         else {{ fn }}.key_text({{ value }}) end
{%- endmacro %}


{#
  The columns of a table that seeds/record_fixes.csv fixes on single records.
  A row naming a column the table lacks, or a table that has no Legacy ID to
  find a record by, stops the build.
#}
{% macro fixed_columns(table_name) %}
    {%- set fixes_seed = ref('record_fixes') -%}
    {%- set out = [] -%}
    {%- if execute -%}
        {%- set known = raw_column_names(table_name) -%}
        {%- set rows = run_query("select distinct column_name from " ~ fixes_seed ~ " where table_name = '" ~ table_name ~ "' order by 1") -%}
        {%- for r in rows -%}
            {%- if r[0] not in known -%}
                {{- exceptions.raise_compiler_error("seeds/record_fixes.csv fixes " ~ table_name ~ "." ~ r[0] ~ ", which is not a column of " ~ table_name) -}}
            {%- endif -%}
            {%- do out.append(r[0]) -%}
        {%- endfor -%}
        {%- if out and table_name not in hashed_tables() -%}
            {{- exceptions.raise_compiler_error("seeds/record_fixes.csv fixes " ~ table_name ~ ", which has no Legacy ID to find a record by") -}}
        {%- endif -%}
    {%- endif -%}
    {{ return(out) }}
{% endmacro %}


{#
  Two CTEs, t (DB167's rows) and c (cleaned), for a dbo model:

      with {{ cleaned_ctes('SightingT', {'End Dec Lat': '...'}) }}
      select ... from c

  overrides  {column: expression} for the few cleaning rules besides
             spelling, written over the cleaned row `c0`.
  content    columns whose raw values make up __content, for finding exact copies.

  Last come the single-record fixes of seeds/record_fixes.csv: a record found
  by its Legacy ID and Date, whose column holds the fix's old value after the
  rules above, gets the new value (NULL where the fix has none). A record that
  does not hold the old value is left alone, and the test
  record_fixes_are_applied stops the build.
#}
{% macro cleaned_ctes(table_name, overrides={}, content=[]) %}
{%- set fixed = fixed_columns(table_name) -%}
t as (
    select * from {{ source('raw', table_name) }}
),
c0 as (
    select {{ cleaned_columns(table_name) }}
           {%- if content %},
           md5(row({{ content | join(', ') }})::text) as __content
           {%- endif %}
    from t {{ cleaned_joins(table_name) }}
),
c as (
    select
    {%- for c in raw_columns(table_name) %}
        {%- set expression = overrides.get(c.name, 'c0.' ~ adapter.quote(c.name)) %}
        {%- if c.name in fixed %}
        case when fix_{{ loop.index }}.table_name is not null then nullif(fix_{{ loop.index }}.new_value, '')::{{ c.data_type }}
             else {{ expression }} end as {{ adapter.quote(c.name) }},
        {%- else %}
        {{ expression }} as {{ adapter.quote(c.name) }},
        {%- endif %}
    {%- endfor %}
        {{ 'c0.__content' if content else 'null::text' }} as __content
    from c0
    {%- for c in raw_columns(table_name) %}
        {%- if c.name in fixed %}
    left join {{ ref('record_fixes') }} fix_{{ loop.index }}
           on fix_{{ loop.index }}.table_name = '{{ table_name }}' and fix_{{ loop.index }}.column_name = '{{ c.name }}'
          and fix_{{ loop.index }}.legacy_id = c0.{{ adapter.quote(hashed_tables()[table_name]) }}::text
          and fix_{{ loop.index }}.record_date = to_char(c0."Date"::date, 'YYYY-MM-DD')
          and fix_{{ loop.index }}.old_value is not distinct from ({{ overrides.get(c.name, 'c0.' ~ adapter.quote(c.name)) }})::text
        {%- endif %}
    {%- endfor %}
)
{% endmacro %}
