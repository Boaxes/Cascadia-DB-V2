{#
  Put a finished build in place of the live schemas, in one transaction.

      dbt build                    # into dbo_next and app_next
      dbt run-operation swap       # then this

  dbo is replaced wholesale: the old one is dropped and dbo_next takes its
  name. app also holds what is never rebuilt -- audit_log and record_diff() --
  so it stays put: the old views and rule_column are dropped, and the new ones
  move in from app_next. Afterwards the database has three schemas again: raw,
  dbo and app. Nothing of the previous build is kept; the backup taken before
  a deploy's build is the way back.

  First the tables the website writes are locked, so a save made now waits a
  few seconds rather than landing in a table that is being replaced. If the
  audit log has an entry newer than the build replayed, the swap stops and
  nothing changes: build again.

  Species and vessels the build gave new ids to are saved into raw's lists
  (macros/lists.sql), in the same transaction.
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
        if to_regnamespace('dbo{{ suffix }}') is null or to_regnamespace('app{{ suffix }}') is null then
            raise exception 'There is no finished build in dbo{{ suffix }} and app{{ suffix }}. Run dbt build first.';
        end if;

        -- Wait for any save in progress, and hold new ones back.
        if to_regnamespace('dbo') is not null then
            lock table dbo."SightingT", dbo."DailyEffortT", dbo."DailyConditionT",
                       dbo."DailyEventT", dbo."SampleT", dbo."TrackT" in exclusive mode;
        end if;
        lock table app.audit_log in exclusive mode;

        if obj_description('dbo{{ suffix }}'::regnamespace, 'pg_namespace') not like '%Complete.%' then
            raise exception 'The build in dbo{{ suffix }} did not complete: a model or test failed, or only part of it was built. Fix that and build again.';
        end if;
        built := substring(obj_description('dbo{{ suffix }}'::regnamespace, 'pg_namespace')
                           from 'entry ([0-9]+)')::bigint;
        select coalesce(max(id), 0) into newest from app.audit_log;
        if built is null or newest <> built then
            raise exception 'The audit log has % entries newer than this build. Run dbt build again, then swap.',
                (select count(*) from app.audit_log where id > coalesce(built, 0));
        end if;

        -- Species and vessels this build gave new ids to keep them from now on.
        {{ remember_new_rows() }}

        -- app: what the previous build made goes.
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
                   where t.relnamespace = 'dbo'::regnamespace
                     and v.relnamespace <> 'dbo'::regnamespace) then
            raise exception 'These views read from dbo and would be dropped with it: %. Move them into the dbt project first.',
                (select string_agg(distinct v.relnamespace::regnamespace || '.' || v.relname, ', ')
                 from pg_depend d join pg_rewrite rw on rw.oid = d.objid
                 join pg_class v on v.oid = rw.ev_class join pg_class t on t.oid = d.refobjid
                 where t.relnamespace = 'dbo'::regnamespace and v.relnamespace <> 'dbo'::regnamespace);
        end if;
        drop schema if exists dbo cascade;
        execute 'alter schema dbo{{ suffix }} rename to dbo';
        comment on schema dbo is null;

        -- app: what this build made comes in.
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
    {% do log("Swapped in. The database has raw, dbo and app.", info=true) %}
{% endmacro %}
