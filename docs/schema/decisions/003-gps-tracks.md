# 003: GPS Tracks in PostGIS, With a DuckLake Copy

**Status:** Decided (2026-11-27, by Brandon, Q-070, Q-071, Q-072, Q-075, Q-076, Q-078, Q-080, Q-082)
**Phase:** 2
**Spec requirements served:** MAP-05, MAP-06, TRACK-01 to TRACK-08, TFM-01 to TFM-08, SQL-01

## Question

Where the track catalog lives, how points are laid out, which copy is the source of truth, how PostGIS is kept in step and at what detail, and how the site reads tracks.

## Findings

- **Volume:** 10,397,499 points across 1,552 tracks: 2,026 at the median, 49,504 at most, one GPS point every 15 s at the median. That is about 116 MB as Parquet with zstd, or 11 bytes a point. It grows by about 1 million points a year.
- **PostGIS can't run spatial queries on DuckLake tables.**
  - pg_ducklake and pg_duckdb run any query that touches a DuckLake table in DuckDB's engine, which cannot call Postgres functions (pg_duckdb issue #615, open since February 2025, milestone "Long term").
  - PostGIS support is an open discussion (#606) with nothing built.
  - DuckLake tables have no GiST index.
  - Extending pg_ducklake would mean a C++ fork of pg_duckdb's planner.

## Options

### Catalog Location

- **A (chosen):** a `ducklake` schema in the same Postgres database. Many readers and writers can work at once, and it's backed up with the database.
- **B:** a DuckDB file, where a single writer locks out the others.
- **C:** a SQLite file, one more file to look after.

### What PostGIS Holds

- **First choice (Q-071), replaced:** every point as a row (10.4 million rows), plus 11 m and 550 m lines with per-vertex step maxima, in three copy tables beside `gold.track`. Brandon rejected it as bloated (Q-078).
- **Chosen (Q-078): one row per track.** `gold.track.geom` is a `MultiLineStringM` holding every GPS point, with M = the point's time. A new part starts where GPS points are more than 60 s apart, the smallest gap the settings allow, so time gaps fall only between parts and the browser applies each user's rules (TRACK-06). Generated columns hold Explore's 550 m line, the point count, the length and the top speed. Effort and sighting maps simplify one track to 11 m on request.
- **Rejected:** lines only (breaks MAP-06).

### Source of Truth and Sync

- **First choice (Q-075), replaced: DuckLake is the source of truth.** Each write went to DuckLake first, then to a new `gold.track` version carrying the DuckLake snapshot ID, with a nightly job to repair Postgres from DuckLake's commit messages. Once Q-078 put every point of every version in `geom`, DuckLake held the same points and history twice.
- **A (chosen, Q-082): Postgres is the source of truth, and DuckLake is a copy.**
  - Each save commits a new `gold.track` version, then rewrites that track's rows in DuckLake from the saved `geom`.
  - A nightly check (TFM-07) rewrites any track whose copy is missing or out of date, and can rebuild the lake from nothing.
- **B:** PostGIS only, dropping DuckLake. One store and no sync, but against V2Spec and Q-028.
- **C:** pg_lake with Iceberg tables. PostGIS works there today, but it's a young, separate service, and Iceberg, not DuckLake.

## Decision

Each `gold.track` version holds its points in `geom`, which the site reads, and is the source of truth. `gold.track` is versioned like every other table (decision 004), with the same four change types, so earlier versions load straight from Postgres (TFM-04). Status is worked out by `track_current`, not stored (Q-080).

**DuckLake layout:**
- One table, `track_point (track_id, version_id, seq, point_time, lon, lat)`, partitioned by year, on the droplet's disk.
- It holds current tracks only. `version_id` names the `gold.track` version the rows were copied from, which the nightly check compares.

**How the site reads:**
- Every map reads PostGIS through the one track component (TRACK-01).
- The SQL page reads points as Parquet exported by year (decision 005), and Export's raw GPS files come from the lake.

Details and diagrams: `ducklake.md`.
