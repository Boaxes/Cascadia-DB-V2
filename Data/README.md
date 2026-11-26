# Data Snapshots

Offline Parquet copies of the source data, so you can explore with DuckDB without connecting to any server. Taken 2026-11-26. All reads were read-only.

```python
import duckdb
duckdb.sql("select * from 'Data/Postgres/app/sighting.parquet' limit 5")
duckdb.sql("select * from 'Data/Postgres/_catalog/columns.csv' where \"table\" = 'sighting'")
```

## Folders

| Folder | Source | Contents |
|---|---|---|
| `MnID/` | `MN ID_snapshot_NOV2026.accdb` (Access) | 20 tables, one Parquet each. Lower-case names, spaces became underscores. |
| `Postgres/` | Live Cascadia Postgres (`SEDB_*` in `.env`) | Schemas `app` (what the website reads) and `dbo` (cleaned DB167 copy), tables and views. |
| `SQLServer/` | DB167 `DB_167282_crcmergedb` (`SQLSERVER_*` in `.env`) | Schema `dbo`, all tables and views. |

Each of `Postgres/` and `SQLServer/` has:
- `<schema>/<table>.parquet`: the data.
- `_catalog/tables.csv`: schema, table, kind (table or view), row count, file.
- `_catalog/columns.csv`: every column with its type, nullability and primary key flag.
- `_catalog/views.sql`: the SQL definition of every view.

## Things To Know

- **Geometry** columns (`geom`, `start_point`, `end_geom` and similar) are stored as WKT text. Use DuckDB spatial (`ST_GeomFromText`) to query them.
- **Not exported from Postgres:** `raw` (a mirror of DB167, use `SQLServer/` instead), `build` and `*_next` (dbt scratch), `elementary`, `public` (logins, feedback, PostGIS and land data) and `app.audit_log*`.
- **Not exported from SQL Server:** `UserT` and `ServerSystemT` (logins and server details).
- **Postgres is cleaned, DB167 is not.** Row counts differ slightly (for example `SightingT` is 118,389 in DB167 and 114,876 in Postgres) because the pipeline drops or merges rows. `dbo.*T` tables exist in both with the same names.
- **JSON, interval and uuid** columns in Postgres, and time, xml, uniqueidentifier and spatial columns in SQL Server, are stored as text. Binary is stored as hex.
- **Track files** (GPS points) are not here; only track metadata and line geometry are.
- **MnID** columns were renamed with underscores; the original Access names are in `mn-id-export/csv/_schema.tsv` in the old repo.

## Refreshing

```
python Data/export_databases.py [postgres|sqlserver|all]
```

Needs `psycopg2-binary`, `pyodbc` and `pyarrow`, and the `.env` file in the repo root. SQL Server views take a few minutes (`SightingV` and `SightingEffortTrackV` are the slow ones).
