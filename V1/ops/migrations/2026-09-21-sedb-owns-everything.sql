-- sedb, the role the application logs in as, owns everything in its
-- database: every schema, table, view, sequence and function in raw, dbo, app
-- and public. It can create, alter and drop anything there, schema changes
-- included, with no permission errors. It is not a superuser, so it still
-- cannot act outside this database (read server files, run shell commands).
--
-- Left alone: objects that belong to an extension (PostGIS), which Postgres
-- manages itself, and the tiger and topology schemas PostGIS installs.
--
-- One transaction. Run once on the server, as postgres:
--   ssh root@<server> "sudo -u postgres psql -d sedb -v ON_ERROR_STOP=1" < this file

BEGIN;

DO $$
DECLARE
  schemas text[] := ARRAY['raw', 'dbo', 'app', 'public'];
  s text;
  r record;
BEGIN
  -- public already belongs to the database owner, which is sedb.
  EXECUTE 'ALTER DATABASE sedb OWNER TO sedb';
  FOREACH s IN ARRAY ARRAY['raw', 'dbo', 'app'] LOOP
    EXECUTE format('ALTER SCHEMA %I OWNER TO sedb', s);
  END LOOP;

  -- Tables, views and materialised views. A table's own sequences (serial and
  -- identity columns) follow it automatically.
  FOR r IN
    SELECT n.nspname, c.relname, c.relkind
    FROM   pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE  n.nspname = ANY (schemas)
      AND  c.relkind IN ('r', 'p', 'v', 'm', 'f')
      AND  NOT EXISTS (SELECT 1 FROM pg_depend d
                       WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid
                         AND d.deptype = 'e')
  LOOP
    EXECUTE format('ALTER %s %I.%I OWNER TO sedb',
                   CASE r.relkind WHEN 'v' THEN 'VIEW'
                                  WHEN 'm' THEN 'MATERIALIZED VIEW'
                                  WHEN 'f' THEN 'FOREIGN TABLE'
                                  ELSE 'TABLE' END,
                   r.nspname, r.relname);
  END LOOP;

  -- Sequences no table owns.
  FOR r IN
    SELECT n.nspname, c.relname
    FROM   pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE  n.nspname = ANY (schemas) AND c.relkind = 'S'
      AND  NOT EXISTS (SELECT 1 FROM pg_depend d
                       WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid
                         AND d.deptype IN ('a', 'i', 'e'))
  LOOP
    EXECUTE format('ALTER SEQUENCE %I.%I OWNER TO sedb', r.nspname, r.relname);
  END LOOP;

  -- Functions and procedures, triggers included.
  FOR r IN
    SELECT p.oid::regprocedure AS sig, p.prokind
    FROM   pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE  n.nspname = ANY (schemas)
      AND  NOT EXISTS (SELECT 1 FROM pg_depend d
                       WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid
                         AND d.deptype = 'e')
  LOOP
    EXECUTE format('ALTER %s %s OWNER TO sedb',
                   CASE r.prokind WHEN 'p' THEN 'PROCEDURE' ELSE 'FUNCTION' END, r.sig);
  END LOOP;

  -- Anything postgres creates here later is open to sedb as well.
  FOREACH s IN ARRAY schemas LOOP
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA %I GRANT ALL ON TABLES TO sedb', s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA %I GRANT ALL ON SEQUENCES TO sedb', s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA %I GRANT ALL ON FUNCTIONS TO sedb', s);
  END LOOP;
END $$;

COMMIT;
