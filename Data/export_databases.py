"""Snapshot the live Postgres and DB167 (SQL Server) into Parquet for offline exploration.

Read-only on both servers. Credentials come from ../.env (never printed).
Usage:  python export_databases.py [postgres|sqlserver|all]
Needs:  psycopg2-binary, pyodbc, pyarrow
Writes: Postgres/<schema>/<table>.parquet, SQLServer/<schema>/<table>.parquet,
        and per database _catalog/{tables,columns,views}.csv plus views.sql
"""
import csv, datetime, decimal, sys, time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ENV = {}
for line in (HERE.parent / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        ENV[k] = v.strip().strip("\"'")

# Postgres: only the cleaned layers. raw is a mirror of DB167 (exported from SQL Server
# instead), build is dbt scratch, public holds logins and PostGIS reference data.
PG_SCHEMAS = ("app", "dbo")
PG_SKIP = {"audit_log", "audit_log_before_cutover_20261021"}
# SQL Server: UserT and ServerSystemT hold logins and server details, so they are left out.
SS_SKIP = {"UserT", "ServerSystemT"}


def to_arrow(names, rows):
    cols = list(zip(*rows)) if rows else [() for _ in names]
    arrays = []
    for name, vals in zip(names, cols):
        vals = list(vals)
        try:
            vals = [v.isoformat() if isinstance(v, datetime.time) else v for v in vals]
            vals = [bytes(v).hex() if isinstance(v, (bytes, bytearray, memoryview)) else v for v in vals]
            vals = [str(v) if isinstance(v, datetime.timedelta) else v for v in vals]
            arrays.append(pa.array(vals))
        except Exception:
            arrays.append(pa.array([None if v is None else str(v) for v in vals], type=pa.string()))
    # all-null columns infer as null type; store them as string
    arrays = [a.cast(pa.string()) if pa.types.is_null(a.type) else a for a in arrays]
    return pa.table(arrays, names=list(names))


def write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def dump(cur, sql, out):
    cur.execute(sql)
    names = [d[0] for d in cur.description]
    rows = cur.fetchall()
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(to_arrow(names, [tuple(r) for r in rows]), out, compression="snappy")
    return len(rows)


def export_postgres():
    import psycopg2
    root = HERE / "Postgres"
    c = psycopg2.connect(host=ENV["SEDB_HOST"], port=ENV["SEDB_PORT"], dbname=ENV["SEDB_DB"],
                         user=ENV["SEDB_USER"], password=ENV["SEDB_PASSWORD"], connect_timeout=20,
                         options="-c default_transaction_read_only=on -c statement_timeout=0")
    c.set_session(readonly=True)
    cur = c.cursor()
    cur.execute("""
        select c.table_schema, c.table_name, t.table_type, c.column_name, c.ordinal_position,
               c.data_type, c.udt_name, c.is_nullable,
               exists (select 1 from information_schema.table_constraints tc
                       join information_schema.key_column_usage k using (constraint_name, table_schema, table_name)
                       where tc.constraint_type='PRIMARY KEY' and tc.table_schema=c.table_schema
                         and tc.table_name=c.table_name and k.column_name=c.column_name)
        from information_schema.columns c
        join information_schema.tables t using (table_schema, table_name)
        where c.table_schema = any(%s) order by 1, 2, 5""", (list(PG_SCHEMAS),))
    cols = [r for r in cur.fetchall() if r[1] not in PG_SKIP]
    write_csv(root / "_catalog" / "columns.csv",
              ["schema", "table", "kind", "column", "position", "data_type", "udt", "nullable", "primary_key"], cols)
    rels = {}
    for r in cols:
        rels.setdefault((r[0], r[1], r[2]), []).append(r)
    tables = []
    for (sch, tbl, kind), cs in sorted(rels.items()):
        sel = []
        for r in cs:
            q = '"%s"' % r[3]
            if r[6] in ("geometry", "geography"):
                q = 'ST_AsText(%s) as %s' % (q, q)
            elif r[6] in ("jsonb", "json", "interval", "uuid", "inet"):
                q = '%s::text as %s' % (q, q)
            sel.append(q)
        t0 = time.time()
        n = dump(cur, 'select %s from "%s"."%s"' % (", ".join(sel), sch, tbl), root / sch / f"{tbl}.parquet")
        tables.append((sch, tbl, "view" if kind == "VIEW" else "table", n, f"{sch}/{tbl}.parquet"))
        print(f"postgres {sch}.{tbl}: {n} rows ({time.time()-t0:.0f}s)", flush=True)
    write_csv(root / "_catalog" / "tables.csv", ["schema", "table", "kind", "rows", "file"], tables)
    cur.execute("select schemaname, viewname, definition from pg_views where schemaname = any(%s) order by 1,2",
                (list(PG_SCHEMAS),))
    views = [r for r in cur.fetchall() if r[1] not in PG_SKIP]
    with open(root / "_catalog" / "views.sql", "w", encoding="utf-8") as f:
        for sch, v, d in views:
            f.write(f"-- {sch}.{v}\ncreate view {sch}.{v} as\n{d.strip()}\n\n")
    c.close()


def export_sqlserver():
    import pyodbc
    root = HERE / "SQLServer"
    d = ENV["SQLSERVER_DRIVER"]
    d = d if d.startswith("{") else "{" + d + "}"
    cs = (f"DRIVER={d};SERVER={ENV['SQLSERVER_HOST']},{ENV['SQLSERVER_PORT']};DATABASE={ENV['SQLSERVER_DATABASE']};"
          f"UID={ENV['SQLSERVER_USER']};PWD={ENV['SQLSERVER_PASSWORD']};ApplicationIntent=ReadOnly;"
          f"{ENV.get('SQLSERVER_EXTRA_PARAMS', '')}")
    c = pyodbc.connect(cs, timeout=30)
    cur = c.cursor()
    cur.execute("""
        select c.TABLE_SCHEMA, c.TABLE_NAME, t.TABLE_TYPE, c.COLUMN_NAME, c.ORDINAL_POSITION, c.DATA_TYPE,
               c.CHARACTER_MAXIMUM_LENGTH, c.IS_NULLABLE,
               case when exists (select 1 from INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                    join INFORMATION_SCHEMA.KEY_COLUMN_USAGE k on k.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
                    where tc.CONSTRAINT_TYPE = 'PRIMARY KEY' and tc.TABLE_SCHEMA = c.TABLE_SCHEMA
                      and tc.TABLE_NAME = c.TABLE_NAME and k.COLUMN_NAME = c.COLUMN_NAME) then 1 else 0 end
        from INFORMATION_SCHEMA.COLUMNS c
        join INFORMATION_SCHEMA.TABLES t on t.TABLE_SCHEMA = c.TABLE_SCHEMA and t.TABLE_NAME = c.TABLE_NAME
        order by 1, 2, 5""")
    cols = [tuple(r) for r in cur.fetchall() if r[1] not in SS_SKIP]
    write_csv(root / "_catalog" / "columns.csv",
              ["schema", "table", "kind", "column", "position", "data_type", "max_length", "nullable", "primary_key"], cols)
    rels = {}
    for r in cols:
        rels.setdefault((r[0], r[1], r[2]), []).append(r)
    tables = []
    for (sch, tbl, kind), cs_ in sorted(rels.items()):
        sel = []
        for r in cs_:
            q = "[%s]" % r[3]
            if r[5] in ("geography", "geometry", "hierarchyid", "xml", "sql_variant", "uniqueidentifier", "time", "datetimeoffset"):
                q = "CAST(%s AS NVARCHAR(MAX)) AS %s" % (q, q)
            sel.append(q)
        t0 = time.time()
        n = dump(cur, "select %s from [%s].[%s]" % (", ".join(sel), sch, tbl), root / sch / f"{tbl}.parquet")
        tables.append((sch, tbl, "view" if kind == "VIEW" else "table", n, f"{sch}/{tbl}.parquet"))
        print(f"sqlserver {sch}.{tbl}: {n} rows ({time.time()-t0:.0f}s)", flush=True)
    write_csv(root / "_catalog" / "tables.csv", ["schema", "table", "kind", "rows", "file"], tables)
    cur.execute("""select s.name, v.name, m.definition from sys.views v
                   join sys.schemas s on s.schema_id = v.schema_id
                   join sys.sql_modules m on m.object_id = v.object_id order by 1, 2""")
    with open(root / "_catalog" / "views.sql", "w", encoding="utf-8") as f:
        for sch, v, d in cur.fetchall():
            f.write(f"-- {sch}.{v}\n{d.strip()}\nGO\n\n")
    c.close()


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("postgres", "all"):
        export_postgres()
    if which in ("sqlserver", "all"):
        export_sqlserver()
