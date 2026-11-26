"""
Local SQL Server copies of DB167, to test against.

    python mirror_sqlserver.py today         DB167_Today: DB167 as it is now
    python mirror_sqlserver.py last-import   DB167_LastImport: DB167 as the live
                                             site last imported it
    python mirror_sqlserver.py both

Each is a real SQL Server database on the local `mssql` service (docker compose
--profile mssql up -d mssql), rebuilt from scratch on every run: the same
tables, column types, keys, identity columns, computed columns, defaults,
indexes, foreign key and views as DB167, then the data.

DB167_Today reads DB167 itself, read only, as import_raw.py does.

DB167_LastImport has no SQL Server to read: the only copy of DB167 as the live
site last imported it is the live site's raw schema, which ops/pull-db.sh
brings into the local cascadia database. Its tables and columns are the ones
that copy has (the old import skipped the two IanDB snapshot tables, and DB167
has since gained four tables and some columns); each column gets DB167's own type; the data comes from Postgres.
Views that need something the older copy lacks, and unique indexes added to
DB167 since, which the older data breaks, are left out and reported.
"""

import argparse
import os
import re
import sys
import time

import psycopg
import pyodbc
from dotenv import load_dotenv

import source

DATABASES = {"today": "DB167_Today", "last-import": "DB167_LastImport"}
COLLATION = "SQL_Latin1_General_CP1_CI_AS"
BATCH = 2000


def local(database="master"):
    password = os.environ.get("MSSQL_SA_PASSWORD", "")
    if not password:
        raise RuntimeError("MSSQL_SA_PASSWORD is not set. See .env.example.")
    conn = pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};SERVER=mssql,1433;UID=sa;"
        f"PWD={{{password}}};DATABASE={database};Encrypt=yes;TrustServerCertificate=yes",
        autocommit=True, timeout=60)
    return conn


# ---------------------------------------------------------------------------
# DB167's structure, read from its catalog
# ---------------------------------------------------------------------------


def catalog(conn):
    """Everything needed to recreate DB167's tables and views."""
    q = lambda sql: conn.execute(sql).fetchall()
    tables = source.tables(conn)
    columns = {}
    for row in q("""
        SELECT t.name, c.name, ty.name, c.max_length, c.precision, c.scale, c.is_nullable,
               c.is_identity, CAST(ic.seed_value AS bigint), CAST(ic.increment_value AS bigint),
               c.is_computed, cc.definition, cc.is_persisted, c.collation_name, c.column_id
        FROM   sys.columns c
        JOIN   sys.tables t ON t.object_id = c.object_id
        JOIN   sys.types ty ON ty.user_type_id = c.user_type_id
        LEFT JOIN sys.identity_columns ic ON ic.object_id = c.object_id AND ic.column_id = c.column_id
        LEFT JOIN sys.computed_columns cc ON cc.object_id = c.object_id AND cc.column_id = c.column_id
        WHERE  SCHEMA_NAME(t.schema_id) = 'dbo'
        ORDER  BY t.name, c.column_id"""):
        columns.setdefault(row[0], []).append({
            "name": row[1], "type": row[2], "max_length": row[3], "precision": row[4], "scale": row[5],
            "nullable": bool(row[6]), "identity": (row[8], row[9]) if row[7] else None,
            "computed": (row[11], bool(row[12])) if row[10] else None, "collation": row[13]})
    keys = {}
    for table, name, kind, clustered, column, ordinal in q("""
        SELECT t.name, kc.name, kc.type, i.type_desc, c.name, ic.key_ordinal
        FROM   sys.key_constraints kc
        JOIN   sys.tables t ON t.object_id = kc.parent_object_id
        JOIN   sys.indexes i ON i.object_id = kc.parent_object_id AND i.index_id = kc.unique_index_id
        JOIN   sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
        JOIN   sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
        ORDER  BY t.name, kc.name, ic.key_ordinal"""):
        entry = keys.setdefault(table, {}).setdefault(name, {"kind": kind, "clustered": clustered, "columns": []})
        entry["columns"].append(column)
    indexes = {}
    for table, name, unique, clustered, column, included, descending in q("""
        SELECT t.name, i.name, i.is_unique, i.type_desc, c.name, ic.is_included_column, ic.is_descending_key
        FROM   sys.indexes i
        JOIN   sys.tables t ON t.object_id = i.object_id
        JOIN   sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
        JOIN   sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
        WHERE  i.is_primary_key = 0 AND i.is_unique_constraint = 0 AND i.type > 0
        ORDER  BY t.name, i.name, ic.is_included_column, ic.key_ordinal"""):
        entry = indexes.setdefault(table, {}).setdefault(
            name, {"unique": bool(unique), "clustered": clustered, "columns": [], "included": []})
        (entry["included"] if included else entry["columns"]).append(column + (" DESC" if descending else ""))
    defaults = q("""
        SELECT t.name, c.name, dc.name, dc.definition
        FROM   sys.default_constraints dc
        JOIN   sys.tables t ON t.object_id = dc.parent_object_id
        JOIN   sys.columns c ON c.object_id = dc.parent_object_id AND c.column_id = dc.parent_column_id""")
    foreign_keys = q("""
        SELECT fk.name, tp.name, cp.name, tr.name, cr.name
        FROM   sys.foreign_keys fk
        JOIN   sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
        JOIN   sys.tables tp ON tp.object_id = fkc.parent_object_id
        JOIN   sys.columns cp ON cp.object_id = fkc.parent_object_id AND cp.column_id = fkc.parent_column_id
        JOIN   sys.tables tr ON tr.object_id = fkc.referenced_object_id
        JOIN   sys.columns cr ON cr.object_id = fkc.referenced_object_id AND cr.column_id = fkc.referenced_column_id""")
    views = source.views(conn)
    return {"tables": tables, "columns": columns, "keys": keys, "indexes": indexes,
            "defaults": defaults, "foreign_keys": foreign_keys, "views": views}


def type_sql(c):
    t = c["type"]
    if t in ("nvarchar", "nchar", "varchar", "char", "varbinary", "binary"):
        length = c["max_length"]
        if length == -1:
            return f"{t}(max)"
        if t in ("nvarchar", "nchar"):
            length //= 2
        return f"{t}({length})"
    if t in ("decimal", "numeric"):
        return f"{t}({c['precision']},{c['scale']})"
    if t in ("time", "datetime2", "datetimeoffset"):
        return f"{t}({c['scale']})"
    return t


def column_sql(c):
    if c["computed"]:
        definition, persisted = c["computed"]
        return f"[{c['name']}] AS {definition}" + (" PERSISTED" if persisted else "")
    sql = f"[{c['name']}] {type_sql(c)}"
    if c["collation"] and c["collation"] != COLLATION:
        sql += f" COLLATE {c['collation']}"
    if c["identity"]:
        sql += f" IDENTITY({c['identity'][0]},{c['identity'][1]})"
    return sql + ("" if c["nullable"] else " NOT NULL")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def create_database(name):
    conn = local()
    conn.execute(f"IF DB_ID('{name}') IS NOT NULL BEGIN "
                 f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [{name}]; END")
    conn.execute(f"CREATE DATABASE [{name}] COLLATE {COLLATION}")
    conn.execute(f"ALTER DATABASE [{name}] SET RECOVERY SIMPLE")
    conn.close()
    return local(name)


def create_tables(dst, cat, only=None):
    """Create each table with its columns, keys and defaults. only: {table: set of columns}."""
    made = {}
    for table in cat["tables"]:
        if only is not None and table not in only:
            continue
        cols = [c for c in cat["columns"][table]
                if only is None or c["name"] in only[table] or c["computed"]]
        lines = [column_sql(c) for c in cols]
        for name, key in cat["keys"].get(table, {}).items():
            if all(any(c["name"] == k for c in cols) for k in key["columns"]):
                kind = "PRIMARY KEY" if key["kind"] == "PK" else "UNIQUE"
                lines.append(f"CONSTRAINT [{name}] {kind} {key['clustered']} ("
                             + ", ".join(f"[{k}]" for k in key["columns"]) + ")")
        dst.execute(f"CREATE TABLE dbo.[{table}] (\n    " + ",\n    ".join(lines) + "\n)")
        made[table] = cols
    names = {t: {c["name"] for c in cols} for t, cols in made.items()}
    for table, column, name, definition in cat["defaults"]:
        if column in names.get(table, ()):
            dst.execute(f"ALTER TABLE dbo.[{table}] ADD CONSTRAINT [{name}] DEFAULT {definition} FOR [{column}]")
    return made


VIEW_NAME = re.compile(r"CREATE\s+VIEW\s+(?:\[?dbo\]?\.)?\[?([^\]\s(]+)", re.I)


def finish(dst, cat, made):
    """Indexes, the foreign key and the views, once the data is in."""
    names = {t: {c["name"] for c in cols} for t, cols in made.items()}
    skipped = []
    for table, indexes in cat["indexes"].items():
        for name, ix in indexes.items():
            needed = [c.replace(" DESC", "") for c in ix["columns"]] + ix["included"]
            if table not in names or not all(c in names[table] for c in needed):
                continue
            sql = (f"CREATE {'UNIQUE ' if ix['unique'] else ''}{ix['clustered']} INDEX [{name}] ON dbo.[{table}] ("
                   + ", ".join(f"[{c.replace(' DESC', '')}]" + (" DESC" if c.endswith(" DESC") else "")
                               for c in ix["columns"]) + ")")
            if ix["included"]:
                sql += " INCLUDE (" + ", ".join(f"[{c}]" for c in ix["included"]) + ")"
            try:
                dst.execute(sql)
            except pyodbc.IntegrityError:
                # A unique index added to DB167 after the data was copied.
                skipped.append(("index", f"{table}.{name}", "the data has duplicates, so it did not exist yet"))
    for name, parent, pcol, ref, rcol in cat["foreign_keys"]:
        if pcol in names.get(parent, ()) and rcol in names.get(ref, ()):
            dst.execute(f"ALTER TABLE dbo.[{parent}] WITH NOCHECK ADD CONSTRAINT [{name}] "
                        f"FOREIGN KEY ([{pcol}]) REFERENCES dbo.[{ref}] ([{rcol}])")
    pending = list(cat["views"])
    while pending:
        progress, still = False, []
        for name, definition in pending:
            try:
                dst.execute(definition)
                # A view renamed in DB167 keeps its old name in its definition,
                # so create it under that name and rename it, as DB167 did.
                created = VIEW_NAME.search(definition).group(1)
                if created != name:
                    dst.execute("EXEC sp_rename ?, ?", f"dbo.{created}", name)
                progress = True
            except pyodbc.Error as exc:
                still.append((name, definition, str(exc).split("]")[-1].strip()))
        if not progress:
            skipped += [("view", n, why) for n, _, why in still]
            break
        pending = [(n, d) for n, d, _ in still]
    return skipped


def load(dst, table, cols, batches):
    """Insert every row, identity values included."""
    insertable = [c for c in cols if not c["computed"]]
    names = ", ".join(f"[{c['name']}]" for c in insertable)
    marks = ", ".join("?" for _ in insertable)
    identity = any(c["identity"] for c in insertable)
    cur = dst.cursor()
    cur.fast_executemany = True
    if identity:
        cur.execute(f"SET IDENTITY_INSERT dbo.[{table}] ON")
    count = 0
    for batch in batches:
        rows = [tuple(r) for r in batch]
        if rows:
            cur.executemany(f"INSERT INTO dbo.[{table}] ({names}) VALUES ({marks})", rows)
            count += len(rows)
    if identity:
        cur.execute(f"SET IDENTITY_INSERT dbo.[{table}] OFF")
    return count


def build_today(cat, src):
    dst = create_database(DATABASES["today"])
    made = create_tables(dst, cat)
    total = 0
    for table, cols in made.items():
        started = time.time()
        names = [c["name"] for c in cols if not c["computed"]]
        n = load(dst, table, cols, source.rows(src, table, names, batch=BATCH))
        total += n
        print(f"  {table:<32} {n:>9,} rows  {time.time() - started:6.1f}s")
    skipped = finish(dst, cat, made)
    report(DATABASES["today"], total, skipped)


def build_last_import(cat):
    pg = psycopg.connect(os.environ.get("LAST_IMPORT_DATABASE_URL",
                                        "postgresql://cascadia:cascadia@db:5432/cascadia"))
    present = {}
    for table, column in pg.execute(
            "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'raw'"):
        present.setdefault(table, set()).add(column)
    only = {t: present[t] for t in cat["tables"] if t in present}
    dst = create_database(DATABASES["last-import"])
    made = create_tables(dst, cat, only)
    total = 0
    for table, cols in made.items():
        started = time.time()
        names = [c["name"] for c in cols if not c["computed"]]
        with pg.cursor(name=f"read_{table}") as cur:
            cur.itersize = BATCH
            cur.execute(f'SELECT {", ".join(chr(34) + n + chr(34) for n in names)} FROM raw."{table}"')
            def batches():
                while True:
                    chunk = cur.fetchmany(BATCH)
                    if not chunk:
                        return
                    yield chunk
            n = load(dst, table, cols, batches())
        total += n
        print(f"  {table:<32} {n:>9,} rows  {time.time() - started:6.1f}s")
    skipped = finish(dst, cat, made)
    missing = [t for t in cat["tables"] if t not in only]
    if missing:
        print(f"  not in the last import: {', '.join(missing)}")
    report(DATABASES["last-import"], total, skipped)


def report(name, total, skipped):
    print(f"{name}: {total:,} rows")
    for kind, name, why in skipped:
        print(f"  {kind} {name} left out: {why}")


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("which", choices=["today", "last-import", "both"])
    args = parser.parse_args()
    src = source.connect()
    cat = catalog(src)
    if args.which in ("today", "both"):
        print(f"building {DATABASES['today']} from DB167")
        build_today(cat, src)
    if args.which in ("last-import", "both"):
        print(f"building {DATABASES['last-import']} from the live site's raw schema")
        build_last_import(cat)
    return 0


if __name__ == "__main__":
    sys.exit(main())
