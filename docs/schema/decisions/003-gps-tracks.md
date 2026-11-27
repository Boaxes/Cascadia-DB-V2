# 003: GPS Tracks in DuckLake and PostGIS

**Status:** Decided (2026-11-27, by Brandon, Q-070, Q-071, Q-072, Q-075, Q-076)
**Phase:** 2
**Spec requirements served:** MAP-05, MAP-06, TRACK-01 to TRACK-08, TFM-01 to TFM-08, SQL-01

## Question

Where the track catalog lives, how points are laid out, which copy is the source of truth, how PostGIS is kept in step and at what detail, and how the site reads tracks.

## Findings

- **Volume:** 10,397,499 points across 1,552 tracks: 2,026 at the median, 49,504 at most, one fix every 15 s at the median. That is about 116 MB as Parquet with zstd, or 11 bytes a point. It grows by about 1 million points a year.
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

- **A (chosen): every point, plus two precomputed lines per track,** at about 11 m (effort and sighting maps) and about 550 m (Explore).
  - Each kept vertex carries its time and the largest time step, distance step and speed among the original fixes it stands for. The browser applies each user's gap rules at any level without reloading (TRACK-06).
  - Cost: about 1 GB in Postgres.
- **B:** every point only, with lines and gaps computed per request. This breaks TRACK-06 and slows Explore.
- **C:** lines only. This breaks MAP-06.

### Source of Truth and Sync

- **A (chosen): DuckLake is the source of truth.**
  - Each track write goes to DuckLake in one transaction, then rebuilds that track's PostGIS rows, stamped with the DuckLake snapshot ID.
  - A nightly check (TFM-07) rebuilds any track whose stamp differs.
- **B:** PostGIS only, dropping DuckLake. One store and no sync, but against V2Spec and Q-028.
- **C:** pg_lake with Iceberg tables. PostGIS works there today, but it's a young, separate service, and Iceberg, not DuckLake.

## Decision

DuckLake is the source of truth for points, and PostGIS holds the copy the site reads.

**DuckLake layout:**
- One table, `track_point (track_id, fix_time, lon, lat)`, partitioned by year, on the droplet's disk.
- Every write is a snapshot, so earlier versions of a track come from DuckLake time travel (TFM-04).
- Track metadata (file name, status, effort, source) is a versioned Postgres table like every other (decision 004).

**How the site reads:**
- Every map reads PostGIS through the one track component (TRACK-01).
- The SQL page reads points as Parquet exported by year (decision 005).

Details and diagrams: `ducklake.md`.
