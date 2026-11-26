{#
  Apply app.audit_log to a table's cleaned rows. This is the one place
  record-level changes happen. In a dbo model:

      with cleaned as ( ...raw, with this table's cleaning... ),
      r as ( {{ replay_rows('cleaned', 'SightingT', 'SightingID') }} )
      select {{ replayed_columns('SightingT', 'r') }}, ...
      from r

  replay_rows() gives every row that exists once the log is applied: the
  cleaned rows, less those a delete removed, plus those the website created.
  Each row carries `__edits`, the newest value of every field an edit set
  (models/dbo/replay/audit_changes.sql).

  replayed_columns() then gives each of the table's own columns with its edit
  applied, in DB167's order and type. edited() does the same for one column
  the dbo model works out itself, such as a derived one: the newest edit wins
  over the derived value, which is what live stores.

  A table's cleaned rows have exactly its DB167 table's columns, so the column
  list is read from raw.
#}

{% macro raw_columns(table_name) %}
    {%- if execute -%}
        {{ return(adapter.get_columns_in_relation(source('raw', table_name))) }}
    {%- else -%}
        {{ return([]) }}
    {%- endif -%}
{% endmacro %}


{% macro replay_rows(base, table_name, key) %}
    {%- set k = adapter.quote(key) -%}
    {#- Columns named one by one rather than b.*, so that column-level lineage
        can follow each of them through. -#}
    select {{ column_list(table_name, 'b') }}, coalesce(c.changes, '{}'::jsonb) as __edits
    from (
        select {{ k }}::text as __key from {{ base }}
        union
        select target_pk from {{ ref('audit_rows') }}
        where target_table = '{{ table_name }}' and state = 'created'
        except
        select target_pk from {{ ref('audit_rows') }}
        where target_table = '{{ table_name }}' and state = 'deleted'
    ) alive
    left join {{ base }} b on b.{{ k }}::text = alive.__key
    left join {{ ref('audit_changes') }} c
           on c.target_table = '{{ table_name }}' and c.target_pk = alive.__key
{% endmacro %}


{% macro edited(column, expression, data_type, edits='__edits') %}
    case when {{ edits }} ? '{{ column }}'
         then ({{ edits }} ->> '{{ column }}')::{{ data_type }}
         else ({{ expression }})::{{ data_type }}
    end
{%- endmacro %}


{% macro replayed_columns(table_name, relation_alias) %}
    {%- set columns = raw_columns(table_name) -%}
    {%- if columns -%}
        {%- for c in columns %}
        {{ edited(c.name, relation_alias ~ '.' ~ adapter.quote(c.name), c.data_type, relation_alias ~ '.__edits') }} as {{ adapter.quote(c.name) }}{{ "," if not loop.last }}
        {%- endfor -%}
    {%- else -%}
        null as __columns_are_known_only_when_the_model_runs
    {%- endif -%}
{% endmacro %}


{#
  A table's own columns, as a plain list: alias."col", ... in DB167's order.
  For a dbo model that selects the replayed columns and then adds its own.
#}
{% macro column_list(table_name, relation_alias) %}
    {%- set columns = raw_columns(table_name) -%}
    {%- if columns -%}
        {%- for c in columns %}
        {{ relation_alias }}.{{ adapter.quote(c.name) }}{{ "," if not loop.last }}
        {%- endfor -%}
    {%- else -%}
        null as __columns_are_known_only_when_the_model_runs
    {%- endif -%}
{% endmacro %}


{#
  The newest audit log entry this build replays, as a number. The build writes
  it on its own schema when it starts (macros/build_schemas.sql); every model
  replays the log only up to it, so the whole build sees one consistent log,
  and the swap refuses if the log has moved on since.
#}
{% macro audit_watermark() %}
    {%- if execute -%}
        {%- set schema = 'dbo' ~ var('schema_suffix', '_next') -%}
        {%- set result = run_query("select coalesce(substring(obj_description(to_regnamespace('" ~ schema ~ "'), 'pg_namespace') from 'entry ([0-9]+)'), '0')") -%}
        {{- result.columns[0].values()[0] -}}
    {%- else -%}
        0
    {%- endif -%}
{% endmacro %}
