{#
  Whether DB167 holds each change in app.audit_log: the db167_state column,
  worked out by comparing every entry with `raw`, DB167 as it was imported.

    applied         DB167 holds the change: an update's new value, a created
                    row, a deleted row gone
    pending         DB167 does not hold it yet
    conflict        DB167 holds something else: a value that is neither the
                    entry's old nor its new value, a row that is not there to
                    change, a TrackID taken by another track
    not_applicable  nothing DB167 holds: an upload or a file edit, the fields
                    the build works out itself (daily_effort_id, track_status,
                    a track's line), any action not known here, and an entry
                    the old Restore put back, which cancels out with its restore

  An update is applied when DB167 holds the new value of the field, or the new
  value of a later entry that changed the same field again. It is pending
  while DB167 still holds its old value, or any value an earlier entry wrote.
  A track's StartTime and EndTime are the exception to "the log's value is
  DB167's value": the log keeps them in UTC and DB167 in Pacific local time,
  so an entry's value is converted to Pacific (app.db167_form) before it is
  compared with raw. The log itself stays in UTC.

  Old values are compared the way the build keeps text: spaces trimmed,
  capitals ignored, empty as NULL, because the log holds the cleaned text and
  DB167 the text as it was typed.

  Each field of an update is checked on its own (db167_fields, a map of the
  entry's DB167 columns to applied, pending or conflict). The entry is applied
  when every one of them is. A value DB167 has no column for (a sighting's
  depth_m) is in no map: only the website holds it.

  Applied is for good, field by field: once DB167 holds a change, what DB167
  does to that field next is DB167's own, and the build stops replaying it
  (models/build/audit_entries.sql), so it can never overwrite DB167's later
  work. A delete is applied once none of the rows it kept is left, if DB167
  ever had the record. A record the website created and later deleted never
  reached DB167 (or was removed again), so its create, its updates and its
  delete are not applicable: the build replays them together, and the record
  stays gone.

  The finished build runs refresh_db167_state() (dbt_project.yml, on-run-end).
  It can also be run on its own after an import:

      dbt run-operation refresh_db167_state
#}


{% macro db167_state_functions() %}
    -- A value as text in a column's type, so the log's spelling of it (a date
    -- as "2026-05-17 08:00:00", a decimal as a string) compares with what raw
    -- holds. A value the type cannot hold comes back as a marker nothing
    -- equals.
    create or replace function app.db167_text(value text, type_name text)
    returns text language plpgsql stable as $fn$
    declare
        result text;
    begin
        if value is null then
            return null;
        end if;
        execute format('select (%L::%s)::text', value, type_name) into result;
        return result;
    exception when others then
        return E'\x01invalid';
    end;
    $fn$;

    -- An entry's value as DB167 holds it, for comparing with raw: app.db167_text(),
    -- and for a track's StartTime and EndTime, which the log keeps in UTC and
    -- DB167 in Pacific local time, the UTC time converted to Pacific first.
    create or replace function app.db167_form(tbl text, col text, value text, type_name text)
    returns text language plpgsql stable as $fn$
    begin
        if tbl = 'TrackT' and col in ('StartTime', 'EndTime') and value is not null then
            return app.db167_text(app.track_time_pacific(value::timestamp)::text, type_name);
        end if;
        return app.db167_text(value, type_name);
    exception when others then
        return E'\x01invalid';
    end;
    $fn$;

    -- Text as the build keeps it, for comparing an entry's old value: the log
    -- holds the cleaned text (spaces trimmed, capitals merged, empty made
    -- NULL), DB167 the text as it was typed.
    create or replace function app.db167_loose(value text, type_name text)
    returns text language sql immutable as $fn$
        select case when type_name = 'text' then lower(nullif(btrim(value), '')) else value end
    $fn$;

    -- The column DB167 numbers a table's rows by (its Primary Key in raw), or
    -- NULL for a table raw does not have.
    create or replace function app.db167_key(table_name text)
    returns text language sql stable as $fn$
        select a.attname::text
        from pg_index i join pg_attribute a on a.attrelid = i.indrelid and a.attnum = any(i.indkey)
        where i.indrelid = to_regclass(format('raw.%I', table_name)) and i.indisprimary
    $fn$;

    -- The state of one entry, as described at the top of this file, and for an
    -- update the state of each of its fields. A field that was applied stays
    -- applied (db167_fields on the entry itself).
    create or replace function app.db167_check(entry_id bigint, out state text, out fields jsonb)
    returns record language plpgsql stable as $fn$
    declare
        e            app.audit_log%rowtype;
        legacy       text;
        raw_key      text;
        record_key   text;
        present      boolean;
        same_file    boolean;
        made         boolean;
        removed      boolean;
        kept         record;
        kept_key     text;
        field        record;
        verdict      text;
        total        integer;
        applied      integer := 0;
        conflicts    integer := 0;
        raw_text     text;
        new_text     text;
        old_text     text;
        raw_loose    text;
        later        boolean;
        earlier      boolean;
    begin
        select * into e from app.audit_log where id = entry_id;
        if not found then
            return;
        end if;

        -- An entry and the old Restore that put it back cancel out.
        if e.restored_by is not null
           or exists (select 1 from app.audit_log o where o.restored_by = e.id) then
            state := 'not_applicable';
            return;
        end if;
        -- An upload, a file edit, or any action not known here.
        if e.action not in ('create', 'update', 'delete', 'associate', 'dissociate', 'restore')
           or to_regclass(format('raw.%I', e.target_table)) is null then
            state := 'not_applicable';
            return;
        end if;

        raw_key := app.db167_key(e.target_table);
        if raw_key is null then
            state := 'not_applicable';
            return;
        end if;

        -- The record, as DB167 knows it: by its Legacy ID where the table's
        -- Primary Key is a hashed id, else by the Primary Key itself.
        select h.legacy_column into legacy from (values
        {%- for table, column in hashed_tables().items() %}
            ('{{ table }}', '{{ column }}'){{ "," if not loop.last }}
        {%- endfor %}
        ) h(table_name, legacy_column) where h.table_name = e.target_table;
        record_key := case when legacy is null then e.target_pk
                           when e.action = 'delete' then coalesce(e.legacy_pk, e.snapshot -> e.target_table -> 0 ->> legacy)
                           else e.legacy_pk end;
        if record_key is null then
            -- A record the website made in a table whose rows DB167 numbers
            -- itself has no Legacy ID, so there is nothing to write to DB167;
            -- any other entry cannot find its record.
            state := case when e.action = 'create' then 'not_applicable' else 'conflict' end;
            return;
        end if;
        execute format('select exists (select 1 from raw.%I where %I::text = $1)', e.target_table, raw_key)
            into present using record_key;

        -- Whether the website made the record, and whether it deleted it again.
        made := exists (select 1 from app.audit_log c
                        where c.action = 'create' and c.target_table = e.target_table and c.target_pk = e.target_pk
                          and c.id < e.id and c.restored_by is null
                          and not exists (select 1 from app.audit_log o where o.restored_by = c.id));
        removed := exists (select 1 from app.audit_log d
                           where d.action = 'delete' and d.target_table = e.target_table
                             and coalesce(d.legacy_pk, d.target_pk) = coalesce(e.legacy_pk, e.target_pk)
                             and d.id > e.id and d.restored_by is null
                             and not exists (select 1 from app.audit_log o where o.restored_by = d.id));

        if e.action = 'delete' then
            -- A record the website made, and DB167 does not hold, was never in
            -- DB167: its create, updates and delete are replayed together.
            if made and not present then
                state := 'not_applicable';
                return;
            end if;
            -- Applied once none of the rows it kept is left.
            if present then
                state := 'pending';
                return;
            end if;
            for kept in
                select t.key as table_name, r.value as copy
                from jsonb_each(coalesce(e.snapshot, '{}')) t
                cross join lateral jsonb_array_elements(
                    case when jsonb_typeof(t.value) = 'array' then t.value else '[]'::jsonb end) r
            loop
                kept_key := app.db167_key(kept.table_name);
                if kept_key is not null and kept.copy ->> kept_key is not null then
                    execute format('select exists (select 1 from raw.%I where %I::text = $1)', kept.table_name, kept_key)
                        into present using kept.copy ->> kept_key;
                    if present then
                        state := 'pending';
                        return;
                    end if;
                end if;
            end loop;
            state := 'applied';
            return;
        end if;

        if e.action = 'create' then
            if not present then
                state := case when removed then 'not_applicable' else 'pending' end;
                return;
            end if;
            -- DB167 may have used the TrackID for a track of its own: the same
            -- file name says it is this one.
            if e.target_table = 'TrackT' and e.changes ? 'TrackFileName' then
                execute 'select lower(btrim("TrackFileName")) is not distinct from lower(btrim($1)) from raw."TrackT" where "TrackID"::text = $2'
                    into same_file using e.changes -> 'TrackFileName' ->> 'new', record_key;
                state := case when same_file then 'applied' else 'conflict' end;
                return;
            end if;
            state := 'applied';
            return;
        end if;

        -- Changes to fields: only those DB167 has a column for.
        select count(*) into total
        from jsonb_object_keys(coalesce(e.changes, '{}')) k
        join pg_attribute a on a.attrelid = format('raw.%I', e.target_table)::regclass
                           and a.attname = k and a.attnum > 0 and not a.attisdropped
        where k <> raw_key;
        if total = 0 then
            state := 'not_applicable';
            return;
        end if;

        if not present then
            if made then
                state := case when removed then 'not_applicable' else 'pending' end;     -- waits for its create
            else
                state := case when removed then 'applied' else 'conflict' end;           -- the record has gone since, or was never there
            end if;
            return;
        end if;

        fields := '{}'::jsonb;
        for field in
            select k.key as name, k.value as change, format_type(a.atttypid, a.atttypmod) as type_name
            from jsonb_each(coalesce(e.changes, '{}')) k
            join pg_attribute a on a.attrelid = format('raw.%I', e.target_table)::regclass
                               and a.attname = k.key and a.attnum > 0 and not a.attisdropped
            where k.key <> raw_key
        loop
            execute format('select %I::text from raw.%I where %I::text = $1', field.name, e.target_table, raw_key)
                into raw_text using record_key;
            new_text := app.db167_form(e.target_table, field.name, field.change ->> 'new', field.type_name);
            old_text := app.db167_form(e.target_table, field.name, field.change ->> 'old', field.type_name);
            raw_loose := app.db167_loose(raw_text, field.type_name);

            -- The entries that changed this field before and after this one.
            select coalesce(bool_or(l.id > e.id and app.db167_form(e.target_table, field.name, l.changes -> field.name ->> 'new', field.type_name)
                                    is not distinct from raw_text), false),
                   coalesce(bool_or(l.id < e.id and (
                       app.db167_loose(app.db167_form(e.target_table, field.name, l.changes -> field.name ->> 'new', field.type_name), field.type_name) is not distinct from raw_loose
                       or app.db167_loose(app.db167_form(e.target_table, field.name, l.changes -> field.name ->> 'old', field.type_name), field.type_name) is not distinct from raw_loose)), false)
            into later, earlier
            from app.audit_log l
            where l.id <> e.id and l.target_table = e.target_table
              and coalesce(l.legacy_pk, l.target_pk) = coalesce(e.legacy_pk, e.target_pk)
              and l.changes ? field.name
              and l.action in ('create', 'update', 'associate', 'dissociate', 'restore')
              and l.restored_by is null
              and not exists (select 1 from app.audit_log o where o.restored_by = l.id);

            if e.db167_fields ->> field.name = 'applied'
               or raw_text is not distinct from new_text or later then
                verdict := 'applied';
                applied := applied + 1;
            elsif raw_loose is not distinct from app.db167_loose(old_text, field.type_name) or earlier then
                verdict := 'pending';
            else
                verdict := 'conflict';
                conflicts := conflicts + 1;
            end if;
            fields := fields || jsonb_build_object(field.name, verdict);
        end loop;

        state := case when conflicts > 0 then 'conflict'
                      when applied = total then 'applied'
                      else 'pending' end;
    end;
    $fn$;

    create or replace function app.db167_state_of(entry_id bigint)
    returns text language sql stable as $fn$
        select (app.db167_check(entry_id)).state
    $fn$;

    -- Check entries against raw: every entry, or just one (the website calls
    -- it for an entry it has just written). Returns how many it checked.
    --
    -- Once DB167 holds a change, it is applied for good: what DB167 does to
    -- that field afterwards is DB167's own change, and the build no longer
    -- replays it over it (models/build/audit_entries.sql). `forget` checks
    -- every entry afresh, for when raw is an older DB167 than the one last
    -- checked against.
    create or replace function app.refresh_db167_state(only_entry bigint default null, forget boolean default false)
    returns integer language plpgsql as $fn$
    declare
        checked integer;
    begin
        if forget then
            update app.audit_log set db167_fields = null where only_entry is null or id = only_entry;
        end if;
        -- An entry is written, and stamped, only when its state or its fields
        -- change, so two builds of the same inputs leave the log as it was.
        with s as materialized (
            select l.id,
                   case when l.db167_state = 'applied' and not forget then 'applied' else c.state end as new_state,
                   coalesce(c.fields, l.db167_fields) as new_fields
            from app.audit_log l cross join lateral app.db167_check(l.id) c
            where only_entry is null or l.id = only_entry
        ), written as (
            update app.audit_log a
            set db167_state = s.new_state,
                db167_fields = s.new_fields,
                db167_checked_at = now()
            from s
            where a.id = s.id
              and (a.db167_state is distinct from s.new_state
                   or a.db167_fields is distinct from s.new_fields
                   or a.db167_checked_at is null)
            returning a.id
        )
        select count(*) into checked from s;
        return checked;
    end;
    $fn$;
{% endmacro %}


{#
  Check every entry against the build's raw. As an operation, after an import:

      dbt run-operation refresh_db167_state
      dbt run-operation refresh_db167_state --args '{forget: true}'
#}
{% macro refresh_db167_state(forget=false) %}
    {#- After a build or a run of this project's models, and on its own as an operation. -#}
    {% if execute and flags.WHICH in ('build', 'run', 'run-operation') %}
        {% do run_query('select app.refresh_db167_state(null, ' ~ ('true' if forget else 'false') ~ ')') %}
        {% set counts = run_query("select db167_state, count(*) from app.audit_log group by 1 order by 1") %}
        {% set parts = [] %}
        {% for row in counts.rows %}{% do parts.append(row[0] ~ ' ' ~ row[1]) %}{% endfor %}
        {% do log('Audit log entries checked against DB167: ' ~ (parts | join(', ')) ~ '.', info=true) %}
    {% endif %}
{% endmacro %}
