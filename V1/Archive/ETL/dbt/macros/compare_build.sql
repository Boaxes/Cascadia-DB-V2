{#
  Compare a finished build, not yet swapped in, with what is live.

      dbt build                            # into dbo_next and app_next
      dbt run-operation compare_build      # instead of swapping

  Every table and view in dbo and app is compared with its counterpart in
  dbo_next and app_next: first their structure (columns, types, constraints,
  indexes, view and function definitions, triggers), then their rows, as
  multisets, both ways. audit_log and record_diff() are left out: they are not
  rebuilt.

  This is the determinism check. Build twice from the same inputs, swapping
  only the first, and this must find nothing: a pipeline whose output depends
  on row order or the clock is not one whose rebuilds can be trusted. It runs
  wherever dbt does.

  Any difference is listed, and the operation fails. Pass
  --args '{known: ["IdentificationsBySightingV"]}' to report a relation
  without failing on it, for a difference already understood.
#}
{% macro compare_build(known=[]) %}
    {%- set suffix = var('schema_suffix', '_next') -%}
    {%- set sql -%}
    create temporary table build_differences (what text, relation text, detail text) on commit preserve rows;

    do $compare$
    declare
        s        record;
        r        record;
        a        bigint;
        b        bigint;
    begin
        if to_regnamespace('dbo{{ suffix }}') is null or to_regnamespace('app{{ suffix }}') is null then
            raise exception 'There is no build to compare in dbo{{ suffix }} and app{{ suffix }}. Run dbt build first.';
        end if;

        -- Structure, with the build's schema names read as the live ones.
        for s in select * from (values ('dbo', 'dbo{{ suffix }}'), ('app', 'app{{ suffix }}')) v(live, built) loop
            create temporary table live_catalog as select * from pg_temp.catalog_lines(s.live, '{{ suffix }}');
            create temporary table built_catalog as select * from pg_temp.catalog_lines(s.built, '{{ suffix }}');
            insert into build_differences
                select 'structure: live only', s.live, line from (select line from live_catalog except select line from built_catalog) x;
            insert into build_differences
                select 'structure: build only', s.live, line from (select line from built_catalog except select line from live_catalog) x;
            drop table live_catalog;
            drop table built_catalog;
        end loop;

        -- Rows, for every relation both sides have.
        for r in
            select l.nspname as live, c.relname
            from pg_class c join pg_namespace l on l.oid = c.relnamespace
            where l.nspname in ('dbo', 'app') and c.relkind in ('r', 'v')
              and c.relname <> 'audit_log'
              and to_regclass(format('%I.%I', l.nspname || '{{ suffix }}', c.relname)) is not null
        loop
            execute format('select count(*) from (select * from %I.%I except all select * from %I.%I) x',
                           r.live, r.relname, r.live || '{{ suffix }}', r.relname) into a;
            execute format('select count(*) from (select * from %I.%I except all select * from %I.%I) x',
                           r.live || '{{ suffix }}', r.relname, r.live, r.relname) into b;
            if a + b > 0 then
                insert into build_differences values
                    ('rows', r.live || '.' || r.relname, a || ' rows only live, ' || b || ' only in the build');
            end if;
        end loop;
    end
    $compare$;
    {%- endset -%}

    {% do run_query(catalog_lines_function()) %}
    {% do run_query(sql) %}
    {% set found = run_query("select what, relation, detail from build_differences order by 1, 2, 3") %}
    {% do run_query("drop table build_differences; drop function pg_temp.catalog_lines(text, text)") %}

    {% set failing = [] %}
    {% for row in found.rows %}
        {% set name = row[1].split('.')[-1] %}
        {% set tag = '  (known)' if name in known else '' %}
        {% do log(row[0] ~ ' | ' ~ row[1] ~ ' | ' ~ row[2] ~ tag, info=true) %}
        {% if name not in known %}{% do failing.append(row) %}{% endif %}
    {% endfor %}
    {% if failing %}
        {{ exceptions.raise_compiler_error(failing | length ~ " difference(s) between the build and what is live, listed above.") }}
    {% else %}
        {% do log("The build matches what is live" ~ (", apart from the known differences listed" if found.rows else "") ~ ".", info=true) %}
    {% endif %}
{% endmacro %}


{#
  One line per structural fact about a schema's relations and functions. The
  build's schema names are written as the live ones -- in view and function
  definitions too, before they are hashed -- so the two sides line up.
#}
{% macro catalog_lines_function() %}
create or replace function pg_temp.catalog_lines(schema_name text, suffix text)
returns table (line text) language sql stable as $fn$
    with named as (
        select replace(replace(l, 'dbo' || suffix || '.', 'dbo.'), 'app' || suffix || '.', 'app.') as l,
               replace(replace(body, 'dbo' || suffix || '.', 'dbo.'), 'app' || suffix || '.', 'app.') as body
        from (
            select 'relation ' || c.relname || ' kind=' || c.relkind::text as l, null::text as body
            from pg_class c where c.relnamespace = schema_name::regnamespace
              and c.relkind in ('r', 'v', 'm', 'S') and c.relname not in ('audit_log', 'audit_log_id_seq')
            union all
            select 'column ' || c.relname || '.' || a.attname || ' ' || format_type(a.atttypid, a.atttypmod)
                   || case when a.attnotnull then ' not null' else '' end
                   || coalesce(' default ' || pg_get_expr(d.adbin, d.adrelid), '')
                   || case when a.attidentity::text <> '' then ' identity' else '' end, null
            from pg_attribute a join pg_class c on c.oid = a.attrelid
            left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
            where c.relnamespace = schema_name::regnamespace and a.attnum > 0 and not a.attisdropped
              and c.relkind in ('r', 'v', 'm') and c.relname <> 'audit_log'
            union all
            select 'constraint ' || c.relname || ' ' || k.conname || ': ' || pg_get_constraintdef(k.oid), null
            from pg_constraint k join pg_class c on c.oid = k.conrelid
            where c.relnamespace = schema_name::regnamespace and c.relname <> 'audit_log'
            union all
            select 'index ' || pg_get_indexdef(i.indexrelid), null
            from pg_index i join pg_class c on c.oid = i.indrelid
            where c.relnamespace = schema_name::regnamespace and c.relname <> 'audit_log'
            union all
            select 'view ' || c.relname, pg_get_viewdef(c.oid, true)
            from pg_class c where c.relnamespace = schema_name::regnamespace and c.relkind in ('v', 'm')
            union all
            select 'trigger ' || pg_get_triggerdef(t.oid), null
            from pg_trigger t join pg_class c on c.oid = t.tgrelid
            where c.relnamespace = schema_name::regnamespace and not t.tgisinternal
            union all
            select 'function ' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')', pg_get_functiondef(p.oid)
            from pg_proc p where p.pronamespace = schema_name::regnamespace and p.proname <> 'record_diff'
        ) raw_lines
    )
    select l || coalesce(' ' || md5(body), '') from named
$fn$
{% endmacro %}
