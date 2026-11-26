-- The app schema: what Django reads and writes.
--
-- Two things live here that are not views: the audit log, and one function
-- that produces the difference between a raw row and its dbo counterpart.

DROP SCHEMA IF EXISTS app CASCADE;
CREATE SCHEMA app;

-- One row per action. Field-level changes go in `changes`; a delete also
-- carries the whole row and its dependents in `snapshot`, which is what makes
-- a delete undoable.
CREATE TABLE app.audit_log (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at  timestamptz NOT NULL DEFAULT now(),
    actor_id     integer,                -- auth_user.id; no FK, Django owns that table
    actor_name   text NOT NULL,          -- denormalised, survives user deletion
    action       text NOT NULL
        CHECK (action IN ('create','update','delete','restore',
                          'upload','associate','dissociate')),
    target_table text NOT NULL,          -- the dbo table, not the app view
    target_pk    text,
    changes      jsonb,                  -- {"field": {"old": ..., "new": ...}}
    snapshot     jsonb,                  -- {"TableName": [row, ...]} on delete
    comment      text,
    restored_by  bigint REFERENCES app.audit_log(id)
);

CREATE INDEX ix_audit_target ON app.audit_log (target_table, target_pk);
CREATE INDEX ix_audit_actor  ON app.audit_log (actor_id, occurred_at DESC);
CREATE INDEX ix_audit_time   ON app.audit_log (occurred_at DESC);

-- Which rule is responsible for which column. Written from ETL/rules/*.py, so
-- the rule files stay the only place a rule is defined. This is attribution at
-- column level rather than per row: a per-row record of which rule touched
-- which value is exactly the log table the diff replaces.
CREATE TABLE app.rule_column (
    rule_id      text NOT NULL,
    description  text NOT NULL,
    target_table text NOT NULL,
    column_name  text NOT NULL,
    PRIMARY KEY (target_table, column_name, rule_id)
);


-- Every field where the frozen DB167 snapshot and the live row disagree.
--
-- One function for every table, because raw and dbo share column names exactly.
-- Columns that exist only in dbo -- geom, species_id, the derived numbers --
-- are additions rather than changes, and are skipped because the comparison
-- only walks keys present on both sides.
CREATE FUNCTION app.record_diff(target_table text, target_pk text)
RETURNS TABLE (field text, original text, current text)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    key_column text;
    raw_row    jsonb;
    dbo_row    jsonb;
BEGIN
    SELECT a.attname INTO key_column
    FROM   pg_index i
    JOIN   pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
    WHERE  i.indrelid = format('dbo.%I', target_table)::regclass AND i.indisprimary;

    EXECUTE format('SELECT to_jsonb(t) FROM raw.%I t WHERE %I::text = $1',
                   target_table, key_column) INTO raw_row USING target_pk;
    EXECUTE format('SELECT to_jsonb(t) FROM dbo.%I t WHERE %I::text = $1',
                   target_table, key_column) INTO dbo_row USING target_pk;

    IF raw_row IS NULL THEN
        RETURN;                     -- added after the import; nothing to compare
    END IF;

    RETURN QUERY
    SELECT r.key,
           r.value,
           CASE WHEN dbo_row IS NULL THEN NULL ELSE dbo_row ->> r.key END
    FROM   jsonb_each_text(raw_row) r
    WHERE  dbo_row IS NULL                      -- the row was deleted
       OR (dbo_row ? r.key AND dbo_row ->> r.key IS DISTINCT FROM r.value)
    ORDER  BY r.key;
END;
$$;
