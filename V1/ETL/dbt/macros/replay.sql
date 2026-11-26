{#
  Apply app.audit_log to a table's rows. This is the one place record-level
  changes happen. In a dbo model:

      r as ( {{ replay_rows('rows', 'SightingT', 'id') }} ),
      s as ( select {{ replayed_columns('SightingT', 'r') }}, ... from r )

  replay_rows() gives every row that exists once the log is applied: the
  rows, less those a delete removed, plus those the website created. Each row
  carries `__edits`, the newest value of every field an edit set
  (models/build/edits.sql), found by the record's Primary Key: the hashed id in
  the 8 tables that have one, DB167's ID in the rest.

  replayed_columns() then gives each of the table's DB167 columns with its
  edit applied, in DB167's order and type. edited() does the same for one
  column the dbo model works out itself: the newest edit wins over the worked
  out value.
#}

{# Each dbo table's Primary Key column. #}
{% macro primary_keys() %}
    {%- set keys = {} -%}
    {%- for t in hashed_tables() -%}{%- do keys.update({t: 'id'}) -%}{%- endfor -%}
    {%- do keys.update({'EventCodeT': 'EventCodeID', 'IndividualT': 'IndividualID', 'ResearchGroupT': 'ResearchGroupID',
                        'SourceT': 'SourceID', 'SpeciesT': 'SpeciesID', 'TagSummaryT': 'TagSummaryID',
                        'TrackCompleteCodeT': 'TrackCompleteCodeID', 'TrackT': 'TrackID', 'VesselListT': 'vessel_id'}) -%}
    {{ return(keys) }}
{% endmacro %}


{#
  Every row of `base` that exists once the log is applied, with `__key`, the
  Primary Key the log names it by (as text), and `__edits`. A row the website
  created has no row in `base`, so every column of `base` is NULL on it and
  its values come from `__edits`.
#}
{% macro replay_rows(base, table_name, key) %}
    {%- set k = adapter.quote(key) -%}
    select b.*, alive.__key, coalesce(c.changes, '{}'::jsonb) as __edits
    from (
        select {{ k }}::text as __key from {{ base }}
        union
        select target_pk from {{ ref('edit_rows') }}
        where target_table = '{{ table_name }}' and state = 'created'
    ) alive
    left join {{ base }} b on b.{{ k }}::text = alive.__key
    left join {{ ref('edits') }} c on c.target_table = '{{ table_name }}' and c.target_pk = alive.__key
    where not exists (select 1 from {{ ref('edit_rows') }} d
                      where d.target_table = '{{ table_name }}' and d.state = 'deleted' and d.target_pk = alive.__key)
{% endmacro %}


{% macro edited(column, expression, data_type, edits='__edits') %}
    case when {{ edits }} ? '{{ column }}'
         then ({{ edits }} ->> '{{ column }}')::{{ data_type }}
         else ({{ expression }})::{{ data_type }}
    end
{%- endmacro %}


{#
  A Foreign Key a website edit can set: as edited(), except that an edit
  naming a record that is not there (the website deleted it, or it is not in
  this copy of DB167) cannot be applied, so the Foreign Key is NULL, an
  orphan, rather than pointing at nothing. An edit that cleared it stays NULL.

      {{ edited_reference('daily_effort_id', 'effort.id', 'DailyEffortT') }} as daily_effort_id
#}
{% macro edited_reference(column, expression, parent, edits='s.__edits') %}
    {%- set data_type = 'bigint' if parent in hashed_tables() else 'integer' -%}
    case when {{ edits }} ? '{{ column }}'
         then (select v.id from (select ({{ edits }} ->> '{{ column }}')::{{ data_type }} as id) v
               where {{ reference_exists(parent, 'v.id') }})
         else ({{ expression }})::{{ data_type }}
    end
{%- endmacro %}


{#
  A Foreign Key copied from DB167 (or set on the website) as it is, kept only
  where the record it names exists: otherwise NULL, an orphan.
#}
{% macro checked_reference(expression, parent) -%}
    (select v.id from (select {{ expression }} as id) v where {{ reference_exists(parent, 'v.id') }})
{%- endmacro %}


{# Whether `id` names a record of `parent` in this build. #}
{% macro reference_exists(parent, id) -%}
    {%- if parent in hashed_tables() -%}
        {{ exists_after_replay(parent, id) }}
    {%- else -%}
        exists (select 1 from {{ ref(parent) }} p where p.{{ adapter.quote(primary_keys()[parent]) }} = {{ id }})
    {%- endif -%}
{%- endmacro %}


{% macro replayed_columns(table_name, relation_alias) %}
    {%- for c in raw_columns(table_name) %}
        {{ edited(c.name, relation_alias ~ '.' ~ adapter.quote(c.name), c.data_type, relation_alias ~ '.__edits') }} as {{ adapter.quote(c.name) }}{{ "," if not loop.last }}
    {%- endfor -%}
{% endmacro %}


{#
  A table's own DB167 columns, as a plain list: alias."col", ... in DB167's
  order. overrides gives an expression for some of them, {column: expression}.
#}
{% macro column_list(table_name, relation_alias, overrides={}) %}
    {%- for c in raw_columns(table_name) %}
        {%- if c.name in overrides %}
        {{ overrides[c.name] }} as {{ adapter.quote(c.name) }}{{ "," if not loop.last }}
        {%- else %}
        {{ relation_alias }}.{{ adapter.quote(c.name) }}{{ "," if not loop.last }}
        {%- endif %}
    {%- endfor -%}
{% endmacro %}


{#
  The newest audit log entry this build replays. The build writes it on its
  own schema when it starts (macros/schemas.sql); every model replays the log
  only up to it, so the whole build sees one log, and the swap refuses if the
  log has moved on since.
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
