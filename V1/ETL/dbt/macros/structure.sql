{#
  Give a built table its structure: NOT NULL, defaults, identity, the primary
  key, unique keys, indexes and triggers, all read from the model's YAML.
  Foreign keys come last, once every table exists: finish_build(), below. Runs as a post-hook, once the table has its final name, so
  every constraint and index gets exactly the name Postgres itself gives it
  -- which is what the live database has. (dbt's own model contracts create
  the table under a temporary name first, and the names come out wrong.)

  In a model's YAML:

      config:
        meta:
          structure:
            primary_key: [SightingID]
            unique: [[code]]
            indexes:
              - {name: ix_sightingt_date, columns: [Date]}
              - {name: ix_sightingt_geom, columns: [geom], using: gist}
            triggers:
              - {name: sighting_geometry, function: sighting_geometry}
      columns:
        - name: DailyEffortID
          quote: true
          data_type: integer
          config:
            meta:
              not_null: true
              default: "0"
              identity: true
              references: {table: DailyEffortT, column: DailyEffortID, name: fk_sightingt_dailyeffortid}

  Because foreign keys are added after every table is built, the order dbt
  builds the tables in depends only on which tables each one reads.
#}
{% macro apply_structure() %}
    {%- set t = this.include(database=false) -%}
    {%- set meta = (model.config.meta or {}).get('structure') or {} -%}
    {%- set sql = [] -%}

    {%- for name, column in model.columns.items() -%}
        {%- set m = column_meta(column) -%}
        {%- set c = adapter.quote(name) -%}
        {%- if m.get('not_null') -%}
            {%- do sql.append('alter table ' ~ t ~ ' alter column ' ~ c ~ ' set not null') -%}
        {%- endif -%}
        {%- if m.get('default') is not none -%}
            {%- do sql.append('alter table ' ~ t ~ ' alter column ' ~ c ~ ' set default ' ~ m.get('default')) -%}
        {%- endif -%}
        {%- if m.get('identity') -%}
            {%- do sql.append('alter table ' ~ t ~ ' alter column ' ~ c ~ ' add generated always as identity') -%}
            {%- do sql.append("select setval(pg_get_serial_sequence('" ~ t ~ "', '" ~ name ~ "'), coalesce((select max(" ~ c ~ ") from " ~ t ~ "), 1))") -%}
        {%- endif -%}
    {%- endfor -%}

    {%- if meta.get('primary_key') -%}
        {%- do sql.append('alter table ' ~ t ~ ' add primary key (' ~ quoted_list(meta.get('primary_key')) ~ ')') -%}
    {%- endif -%}
    {%- for columns in meta.get('unique', []) -%}
        {%- do sql.append('alter table ' ~ t ~ ' add unique (' ~ quoted_list(columns) ~ ')') -%}
    {%- endfor -%}

    {%- for index in meta.get('indexes', []) -%}
        {%- do sql.append('create index ' ~ adapter.quote(index.name) ~ ' on ' ~ t ~ ' using ' ~ index.get('using', 'btree') ~ ' (' ~ quoted_list(index.columns) ~ ')') -%}
    {%- endfor -%}

    {%- for trigger in meta.get('triggers', []) -%}
        {%- do sql.append('create trigger ' ~ adapter.quote(trigger.name) ~ ' before insert or update on ' ~ t ~ ' for each row execute function ' ~ adapter.quote(this.schema) ~ '.' ~ adapter.quote(trigger.function) ~ '()') -%}
    {%- endfor -%}

    {{ sql | join(';\n') }}
{%- endmacro %}


{% macro quoted_list(columns) -%}
    {%- set out = [] -%}
    {%- for c in columns -%}{%- do out.append(adapter.quote(c)) -%}{%- endfor -%}
    {{ out | join(', ') }}
{%- endmacro %}


{# A column's meta: under config, where dbt v2 wants it, or at the top level. #}
{% macro column_meta(column) -%}
    {%- set config = column.get('config') or {} -%}
    {{ return((config.get('meta') if config.get('meta') else none) or column.get('meta') or {}) }}
{%- endmacro %}


{#
  The end of a build (on-run-end). If every model was built and every test
  ran and passed (a test set to warn may warn), add the foreign keys -- now
  that every table exists -- and mark the build complete, which is what
  `run-operation swap` looks for. If anything failed or was skipped, only part
  of the project was built, or the tests did not run (`dbt run` rather than
  `dbt build`), the build is left unmarked and cannot be swapped in.
#}
{% macro finish_build(results) %}
    {%- if not execute or flags.WHICH not in ('build', 'run') -%}{{ return('') }}{%- endif -%}
    {%- set schema = 'dbo' ~ var('schema_suffix', '_next') -%}
    {%- set failed = [] -%}
    {%- for r in results -%}{%- if r.status in ['error', 'fail', 'skipped', 'runtime error'] -%}{%- do failed.append(r.node.name) -%}{%- endif -%}{%- endfor -%}
    {#- This project's own models only: Elementary's are built separately. -#}
    {%- set built = results | map(attribute='node') | selectattr('resource_type', 'equalto', 'model') | selectattr('package_name', 'equalto', project_name) | list | length -%}
    {%- set models = graph.nodes.values() | selectattr('resource_type', 'equalto', 'model') | selectattr('package_name', 'equalto', project_name) | rejectattr('config.materialized', 'equalto', 'ephemeral') | list | length -%}
    {%- if failed -%}
        {%- do log('Not marking the build complete, so it cannot be swapped in. Failed or skipped: ' ~ (failed | join(', ')), info=true) -%}
        {{ return('') }}
    {%- endif -%}
    {%- if built < models -%}
        {%- do log('Only ' ~ built ~ ' of ' ~ models ~ ' models were built; not marking the build complete.', info=true) -%}
        {{ return('') }}
    {%- endif -%}
    {%- set tested = results | map(attribute='node') | selectattr('resource_type', 'equalto', 'test') | selectattr('package_name', 'equalto', project_name) | list | length -%}
    {%- set tests = graph.nodes.values() | selectattr('resource_type', 'equalto', 'test') | selectattr('package_name', 'equalto', project_name) | list | length -%}
    {%- if tested < tests -%}
        {%- do log('Only ' ~ tested ~ ' of ' ~ tests ~ ' tests ran; not marking the build complete. Use dbt build, which runs them.', info=true) -%}
        {{ return('') }}
    {%- endif -%}
    {%- set sql = [] -%}
    {%- for node in graph.nodes.values() if node.resource_type == 'model' and node.schema == schema -%}
        {%- for name, column in node.columns.items() -%}
            {%- set r = column_meta(column).get('references') -%}
            {%- if r -%}
                {%- do sql.append('alter table ' ~ adapter.quote(schema) ~ '.' ~ adapter.quote(node.alias) ~ ' add constraint ' ~ adapter.quote(r.name) ~ ' foreign key (' ~ adapter.quote(name) ~ ') references ' ~ adapter.quote(schema) ~ '.' ~ adapter.quote(r.table) ~ ' (' ~ adapter.quote(r.column) ~ ')') -%}
            {%- endif -%}
        {%- endfor -%}
    {%- endfor -%}
    {%- do sql.append("comment on schema " ~ adapter.quote(schema) ~ " is '" ~ ('Built from app.audit_log up to entry ' ~ audit_watermark() ~ '. ' ~ complete_mark()) ~ "'") -%}
    {%- do run_query(sql | join(';\n')) -%}
    {%- do log('Build complete: ' ~ (sql | length - 1) ~ ' foreign keys added. It can be swapped in.', info=true) -%}
    {{ return('') }}
{% endmacro %}


{# What finish_build writes on a build's dbo schema, and swap looks for. #}
{% macro complete_mark() -%}
    Complete: every model built, every test passed.
{%- endmacro %}
