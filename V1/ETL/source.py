"""
DB167 — the MS SQL Server database this project replaces.

Read only. Everything here selects; nothing writes. The import runs once, and
after it DB167 is retired, so there is deliberately no code that could modify
it.

Unlike V1's reader, this one does not turn every value into text and does not
filter by research group. The types in DB167 are already correct, and V2 keeps
every row.
"""

import os

import pyodbc

# The two IanDB snapshots are leftovers from an abandoned migration. They use
# different column names from everything else and nothing references them.
SKIP_TABLES = {"DailyEffortT_IanDB_SnapshotT", "SightingT_IanDB_SnapShotT"}


def connect():
    """A read-only connection, from DB167_ODBC in the environment."""
    dsn = os.environ.get("DB167_ODBC", "").strip()
    if not dsn:
        raise RuntimeError(
            "DB167_ODBC is not set. Copy .env.example to .env and fill it in."
        )
    conn = pyodbc.connect(dsn, readonly=True, timeout=60)
    conn.timeout = 300
    return conn


# ---------------------------------------------------------------------------
# Catalog
#
# Read from the system views rather than from etl/Schema.sql, which is stale:
# it lists 32 tables where the database has 35, and its types predate the
# columns being given proper ones.
# ---------------------------------------------------------------------------


def tables(conn):
    """Base table names, in catalog order, minus the two snapshots."""
    rows = conn.execute(
        """
        SELECT t.name
        FROM   sys.tables t
        JOIN   sys.schemas s ON s.schema_id = t.schema_id
        WHERE  s.name = 'dbo'
        ORDER  BY t.name
        """
    ).fetchall()
    return [r[0] for r in rows if r[0] not in SKIP_TABLES]


def views(conn):
    """View names and their T-SQL definitions."""
    rows = conn.execute(
        """
        SELECT v.name, m.definition
        FROM   sys.views v
        JOIN   sys.schemas s ON s.schema_id = v.schema_id
        JOIN   sys.sql_modules m ON m.object_id = v.object_id
        WHERE  s.name = 'dbo'
        ORDER  BY v.name
        """
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def columns(conn, table):
    """
    Column definitions in ordinal order.

    Each is a dict: name, type, max_length (characters, -1 for max), precision,
    scale, nullable, is_identity, is_computed.
    """
    rows = conn.execute(
        """
        SELECT c.name,
               ty.name                AS type_name,
               c.max_length,
               c.precision,
               c.scale,
               c.is_nullable,
               c.is_identity,
               c.is_computed
        FROM   sys.columns c
        JOIN   sys.types   ty ON ty.user_type_id = c.user_type_id
        WHERE  c.object_id = OBJECT_ID(?)
        ORDER  BY c.column_id
        """,
        f"dbo.{table}",
    ).fetchall()
    out = []
    for r in rows:
        # sys.columns.max_length is bytes. The double-byte types report twice
        # the character count, and -1 means the (max) types.
        chars = r[2]
        if r[1] in ("nvarchar", "nchar") and chars not in (None, -1):
            chars //= 2
        out.append(
            {
                "name": r[0],
                "type": r[1],
                "max_length": chars,
                "precision": r[3],
                "scale": r[4],
                "nullable": bool(r[5]),
                "is_identity": bool(r[6]),
                "is_computed": bool(r[7]),
            }
        )
    return out


def primary_key(conn, table):
    """The primary key's columns in key order, or [] if the table has none."""
    rows = conn.execute(
        """
        SELECT c.name
        FROM   sys.indexes i
        JOIN   sys.index_columns ic ON ic.object_id = i.object_id
                                   AND ic.index_id  = i.index_id
        JOIN   sys.columns c ON c.object_id = ic.object_id
                            AND c.column_id = ic.column_id
        WHERE  i.object_id = OBJECT_ID(?) AND i.is_primary_key = 1
        ORDER  BY ic.key_ordinal
        """,
        f"dbo.{table}",
    ).fetchall()
    return [r[0] for r in rows]


def unique_constraints(conn, table):
    """Unique indexes that are not the primary key, as lists of columns."""
    rows = conn.execute(
        """
        SELECT i.name, c.name
        FROM   sys.indexes i
        JOIN   sys.index_columns ic ON ic.object_id = i.object_id
                                   AND ic.index_id  = i.index_id
        JOIN   sys.columns c ON c.object_id = ic.object_id
                            AND c.column_id = ic.column_id
        WHERE  i.object_id = OBJECT_ID(?)
          AND  i.is_unique = 1 AND i.is_primary_key = 0
          AND  ic.is_included_column = 0
        ORDER  BY i.name, ic.key_ordinal
        """,
        f"dbo.{table}",
    ).fetchall()
    out = {}
    for index_name, column in rows:
        out.setdefault(index_name, []).append(column)
    return out


def indexes(conn, table):
    """
    Non-unique, non-primary indexes: {name: {"columns": [...], "included": [...]}}.

    Recreated on dbo in Phase 2. Each was a decision made against real Access
    query patterns, so dropping them would slow the front ends after the relink.
    """
    rows = conn.execute(
        """
        SELECT i.name, c.name, ic.is_included_column, ic.is_descending_key
        FROM   sys.indexes i
        JOIN   sys.index_columns ic ON ic.object_id = i.object_id
                                   AND ic.index_id  = i.index_id
        JOIN   sys.columns c ON c.object_id = ic.object_id
                            AND c.column_id = ic.column_id
        WHERE  i.object_id = OBJECT_ID(?)
          AND  i.is_primary_key = 0 AND i.is_unique = 0
          AND  i.type_desc <> 'HEAP'
        ORDER  BY i.name, ic.is_included_column, ic.key_ordinal
        """,
        f"dbo.{table}",
    ).fetchall()
    out = {}
    for name, column, included, descending in rows:
        entry = out.setdefault(name, {"columns": [], "included": []})
        if included:
            entry["included"].append(column)
        else:
            entry["columns"].append(column + (" DESC" if descending else ""))
    return out


def rows(conn, table, column_names, batch=5000):
    """
    Every row, in batches, with the database's own types preserved.

    """
    select = ", ".join(f"[{c}]" for c in column_names)
    cur = conn.execute(f"SELECT {select} FROM dbo.[{table}]")
    while True:
        chunk = cur.fetchmany(batch)
        if not chunk:
            return
        yield chunk
