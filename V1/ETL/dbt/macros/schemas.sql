{#
  Every model goes in the schema its folder names (build, dbo or app) plus the
  build's suffix, `_next` by default: a build writes beside the schemas the
  website uses, and `dbt run-operation swap` moves the result into place.
  Elementary's own models keep their schema as it is.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- elif node.package_name == 'elementary' -%}
        {{ custom_schema_name | trim }}
    {%- else -%}
        {{ custom_schema_name | trim }}{{ var('schema_suffix', '_next') }}
    {%- endif -%}
{%- endmacro %}


{#
  Every build starts from empty schemas: build_next, dbo_next and app_next are
  dropped and created again, so nothing from an earlier or a failed build is
  left in them. The build writes on dbo_next the newest audit log entry it
  replays (the watermark, macros/replay.sql), so every model replays the same
  log and the swap can tell whether the log has moved on since.

  Only `dbt build`, `dbt run` and `dbt seed` do this, and `dbt seed` only for
  build_next, where the seeds go.
#}
{% macro prepare_next_schemas() %}
    {#- Only when this project's models are being built: `dbt run --select
        elementary` must not empty a build in progress. -#}
    {% set ours = [] %}
    {% for r in selected_resources if r.startswith('model.' ~ project_name ~ '.') %}{% do ours.append(r) %}{% endfor %}
    {% if execute and flags.WHICH in ('build', 'run') and ours %}
        {% set suffix = var('schema_suffix', '_next') %}
        {% if suffix == '' %}
            {{ exceptions.raise_compiler_error("schema_suffix is empty: a build would drop the live schemas.") }}
        {% endif %}
        {% for name in ['build', 'dbo', 'app'] %}
            {% set schema = api.Relation.create(database=target.database, schema=name ~ suffix) %}
            {% do adapter.drop_schema(schema) %}
            {% do adapter.create_schema(schema) %}
        {% endfor %}
        {% do run_query(dbo_functions('"dbo' ~ suffix ~ '"')) %}
        {% do run_query(build_functions('"build' ~ suffix ~ '"')) %}
        {#- With --vars '{replay: false}' the build applies no edits at all: the
            first build of a new process, whose ids the audit log is then moved
            onto (ETL/move_to_hashed_keys.py). -#}
        {% set newest = run_query('select coalesce(max(id), 0) from app.audit_log').columns[0].values()[0] if var('replay', true) else 0 %}
        {% do run_query('comment on schema "dbo' ~ suffix ~ '" is \'Built from app.audit_log up to entry ' ~ newest ~ '.\'') %}
    {% endif %}
{% endmacro %}


{#
  The tables the build reads that are neither DB167 nor rebuilt: created empty
  the first time, never dropped.

    app.audit_log       every change made on the website (Django/datahealth/audit.py),
                        and whether DB167 holds it (macros/db167_state.sql)
    app.track_geometry  one row per GPS file in the bucket, with its line
                        (Django/datahealth/gps/tracks.py writes it), and the
                        TrackID of the record a file no track names gets
    app.vessel_number   each vessel's vessel_id, so it never changes once given;
                        the swap adds the vessels a build met for the first time
    app.pipeline_run    one row per run of the daily pipeline workflow, for the
                        list of recent runs on the pipeline's report
                        (ETL/pipeline_run.py writes it, ETL/site.py reads it);
                        the build and the swap never touch it
#}
{% macro persistent_tables() %}
    {% if execute %}
    create schema if not exists app;
    create table if not exists app.audit_log (
        id           bigint generated always as identity primary key,
        occurred_at  timestamptz not null default now(),
        actor_id     integer,
        actor_name   text not null,
        action       text not null check (action in ('create', 'update', 'delete', 'restore', 'upload',
                                                     'associate', 'dissociate', 'edit_file')),
        target_table text not null,
        target_pk    text,
        changes      jsonb,
        snapshot     jsonb,
        comment      text,
        restored_by  bigint references app.audit_log (id)
    );
    -- A log made before edit_file existed has the shorter list of actions.
    alter table app.audit_log drop constraint if exists audit_log_action_check;
    alter table app.audit_log add constraint audit_log_action_check
        check (action in ('create', 'update', 'delete', 'restore', 'upload',
                          'associate', 'dissociate', 'edit_file'));
    -- The Legacy ID (DB167's own ID) of the record an entry is about, in the 8
    -- tables with a hashed Primary Key: if DB167 changes one of the record's
    -- key columns, its id changes, and the build finds it by this instead
    -- (models/build/audit_entries.sql).
    alter table app.audit_log add column if not exists legacy_pk text;
    -- Whether DB167 holds the change: pending, applied, conflict or
    -- not_applicable, worked out against raw after every build
    -- (macros/db167_state.sql).
    alter table app.audit_log add column if not exists db167_state text not null default 'pending'
        check (db167_state in ('pending', 'applied', 'conflict', 'not_applicable'));
    alter table app.audit_log add column if not exists db167_checked_at timestamptz;
    -- For an update, how each of its DB167 columns stands: {"Comments": "applied", ...}.
    alter table app.audit_log add column if not exists db167_fields jsonb;
    create table if not exists app.track_geometry (
        object_key  text primary key,
        etag        text,
        geom        geometry(MultiLineString, 4326),
        point_count integer,
        length_nm   numeric(12, 3),
        built_at    timestamptz not null default now()
    );
    -- The TrackID of the track record a file gets when no track names it
    -- (models/build/bucket_tracks.sql), kept once given.
    alter table app.track_geometry add column if not exists track_id integer unique;
    -- The file's first and last time, in UTC: what the build reads to tell which
    -- of the two hours a Pacific time in the autumn clock change means
    -- (macros/track_times.sql). NULL until the file is read again.
    alter table app.track_geometry add column if not exists first_time timestamp;
    alter table app.track_geometry add column if not exists last_time timestamp;
    create table if not exists app.vessel_number (
        vessel_key  text primary key,
        vessel_id   integer not null unique
    );
    create table if not exists app.pipeline_run (
        run_id         text primary key,
        started_at     timestamptz not null,
        finished_at    timestamptz,
        result         text not null,
        git_commit     text,
        run_url        text,
        deployment_url text,
        tests_passed   integer,
        tests_failed   integer
    );

    -- The fields of a dbo record whose value differs from DB167's, for the
    -- history window on a record's page (Django/survey/history.py). The record
    -- is found by its dbo Primary Key, and DB167's row by the Legacy ID the
    -- dbo record carries.
    create or replace function app.record_diff(target_table text, target_pk text)
    returns table (field text, original text, current text)
    language plpgsql stable as $fn$
    declare
        dbo_key  text;
        raw_key  text;
        legacy   text;
        raw_row  jsonb;
        dbo_row  jsonb;
    begin
        select a.attname into dbo_key
        from pg_index i join pg_attribute a on a.attrelid = i.indrelid and a.attnum = any(i.indkey)
        where i.indrelid = format('dbo.%I', target_table)::regclass and i.indisprimary;
        select a.attname into raw_key
        from pg_index i join pg_attribute a on a.attrelid = i.indrelid and a.attnum = any(i.indkey)
        where i.indrelid = format('raw.%I', target_table)::regclass and i.indisprimary;

        execute format('select to_jsonb(t) from dbo.%I t where %I::text = $1', target_table, dbo_key)
            into dbo_row using target_pk;
        legacy := case when dbo_key = raw_key then target_pk else dbo_row ->> raw_key end;
        if legacy is null then
            return;
        end if;
        execute format('select to_jsonb(t) from raw.%I t where %I::text = $1', target_table, raw_key)
            into raw_row using legacy;
        if raw_row is null then
            return;                     -- added after the import; nothing to compare
        end if;

        return query
        select r.key, r.value, case when dbo_row is null then null else dbo_row ->> r.key end
        from jsonb_each_text(raw_row) r
        where dbo_row is null
           or (dbo_row ? r.key and dbo_row ->> r.key is distinct from r.value)
        order by r.key;
    end;
    $fn$;
    {{ track_time_functions() }}
    {{ db167_state_functions() }}
    {% endif %}
{% endmacro %}


{# The same, on its own: dbt run-operation create_persistent_tables #}
{% macro create_persistent_tables() %}
    {% do run_query(persistent_tables()) %}
    {% do log("app.audit_log, app.track_geometry, app.vessel_number, app.pipeline_run and app.record_diff are in place.", info=true) %}
{% endmacro %}
