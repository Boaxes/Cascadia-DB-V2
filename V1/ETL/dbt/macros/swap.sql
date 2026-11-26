{#
  Put a finished build in place, in one transaction. This is the step the
  pipeline's workflow and its report call publishing: the build is a new copy
  of the data beside the live one, and publishing is the quick final step that
  makes it the live one, done only when every test passed.

      dbt build                    # into build_next, dbo_next and app_next
      dbt run-operation swap       # then this

  build and dbo are replaced wholesale. app also holds what is never rebuilt
  (audit_log, track_geometry, vessel_number, record_diff), so it stays: the
  previous build's views and rule_column are dropped, and the new ones move in
  from app_next.

  First the tables the website writes are locked, so a save made now waits a
  few seconds rather than landing in a table that is being replaced. If the
  audit log has an entry newer than the build replayed, the swap stops and
  nothing changes: build again. Vessels the build met for the first time keep
  their vessel_id from now on (app.vessel_number), and bucket files with no
  track record keep their TrackID (app.track_geometry.track_id).
#}
{% macro swap() %}
    {%- set suffix = var('schema_suffix', '_next') -%}
    {%- if suffix == '' -%}
        {{ exceptions.raise_compiler_error("schema_suffix is empty: there is no build to swap in.") }}
    {%- endif -%}
    {%- set sql -%}
    do $swap$
    declare
        built    bigint;
        newest   bigint;
        object   record;
    begin
        if to_regnamespace('dbo{{ suffix }}') is null or to_regnamespace('app{{ suffix }}') is null
           or to_regnamespace('build{{ suffix }}') is null then
            raise exception 'There is no finished build in build{{ suffix }}, dbo{{ suffix }} and app{{ suffix }}. Run dbt build first.';
        end if;

        -- Wait for any save in progress, and hold new ones back.
        if to_regclass('dbo."SightingT"') is not null then
            lock table dbo."SightingT", dbo."DailyEffortT", dbo."DailyConditionT",
                       dbo."DailyEventT", dbo."SampleT", dbo."TrackT" in exclusive mode;
        end if;
        lock table app.audit_log in exclusive mode;

        if position('{{ complete_mark() }}' in coalesce(obj_description('dbo{{ suffix }}'::regnamespace, 'pg_namespace'), '')) = 0 then
            raise exception 'The build in dbo{{ suffix }} did not complete: a model or test failed, the tests did not run, or only part of it was built. Fix that and run dbt build again.';
        end if;
        built := substring(obj_description('dbo{{ suffix }}'::regnamespace, 'pg_namespace')
                           from 'entry ([0-9]+)')::bigint;
        select coalesce(max(id), 0) into newest from app.audit_log;
        if built is null or newest <> built then
            raise exception 'The audit log has % entries newer than this build. Run dbt build again, then swap.',
                (select count(*) from app.audit_log where id > coalesce(built, 0));
        end if;

        insert into app.vessel_number (vessel_key, vessel_id)
        select vessel_key, vessel_id from build{{ suffix }}.vessels where is_new
        on conflict (vessel_key) do nothing;
        update app.track_geometry g set track_id = b."TrackID"
        from build{{ suffix }}.bucket_tracks b
        where b.is_new and g.object_key = b.file_name and g.track_id is null;

        for object in
            select c.relname, c.relkind from pg_class c
            where c.relnamespace = 'app'::regnamespace
              and (c.relkind = 'v' or c.relname = 'rule_column')
        loop
            execute format('drop %s app.%I cascade',
                           case object.relkind when 'v' then 'view' else 'table' end, object.relname);
        end loop;

        -- Anything outside dbo that reads from it would go with it, silently.
        -- Refuse instead, and say what it is.
        if exists (select 1 from pg_depend d
                   join pg_rewrite rw on rw.oid = d.objid
                   join pg_class v on v.oid = rw.ev_class
                   join pg_class t on t.oid = d.refobjid
                   where t.relnamespace = to_regnamespace('dbo')
                     and v.relnamespace not in (to_regnamespace('dbo'))) then
            raise exception 'These views read from dbo and would be dropped with it: %. Move them into the dbt project first.',
                (select string_agg(distinct v.relnamespace::regnamespace || '.' || v.relname, ', ')
                 from pg_depend d join pg_rewrite rw on rw.oid = d.objid
                 join pg_class v on v.oid = rw.ev_class join pg_class t on t.oid = d.refobjid
                 where t.relnamespace = to_regnamespace('dbo') and v.relnamespace <> to_regnamespace('dbo'));
        end if;
        drop schema if exists dbo cascade;
        drop schema if exists build cascade;
        execute 'alter schema dbo{{ suffix }} rename to dbo';
        execute 'alter schema build{{ suffix }} rename to build';
        comment on schema dbo is null;

        for object in
            select c.relname, c.relkind from pg_class c
            where c.relnamespace = 'app{{ suffix }}'::regnamespace and c.relkind in ('v', 'r')
        loop
            execute format('alter %s app{{ suffix }}.%I set schema app',
                           case object.relkind when 'v' then 'view' else 'table' end, object.relname);
        end loop;
        execute 'drop schema app{{ suffix }}';
    end
    $swap$;
    {%- endset -%}
    {% do run_query(sql) %}
    {% do log("Swapped in. The database has raw, build, dbo and app.", info=true) %}
{% endmacro %}
