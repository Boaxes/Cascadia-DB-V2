# Phase 2: Schema And DuckLake

**Goal:** agree on exactly what the clean data looks like (the gold tier), how GPS tracks are stored, and how changes are audited, so that synthetic data can be generated from it in Phase 4.

**Writes:** `docs/schema/`, plus the workflow logs and `scratch/`.
**Branch:** `phase-2-schema`.
**Builds on:** the approved spec. The schema serves the pages and queries the spec describes, and nothing more.

## Ground Rules

- Design the **gold tier** only: data as it looks after cleaning and merging. Do not design dbt models, staging layers or the merge of the catalogs. Do design so that a later dbt job can write these tables directly (stable keys, plus load and run metadata columns).
- The data is historical, so reads dominate and edits are rare. Optimise for reading: the right B-tree indexes, GiST for geometry, BRIN for time on large tables, and materialized views for summaries the spec shows. Justify each index by naming the query it serves.
- Target PostgreSQL 18 with PostGIS 3.6, the same as V1's production.
- Do all exploration with DuckDB on `Data/`. Put working scripts in `scratch/`. Save the queries behind every claim in `docs/schema/profile_queries.sql` so they can be re-run.

## Steps

### 1. Profile The Data

Write `docs/schema/data-profile.md`. For each entity (sighting, effort, daily condition and event, track, sample, identification, individual, species, vessel, research group, and the MnID tables), record:

- The source tables and how they relate (V1 `app`, cleaned `dbo`, raw DB167, MnID).
- Row counts, key columns, uniqueness, null rates, value ranges, distinct values for categorical columns, date spans, and geographic extent.
- Quirks a schema must handle: for example the 815 MnID alias reconciliations, retired IDs, sightings without effort, and tracks with gaps.

### 2. Decide The Open Design Questions

For each question, write a short decision record in `docs/schema/decisions/NNN-title.md` (template: [decision-record-template.md](decision-record-template.md)). Ask Brandon before marking it decided. At minimum:

- **Catalogs:** one generic photo-ID model (catalog, individual, identification, alias) that MnID, Bm and ErId all fit, against a set of tables per catalog. How individuals link to sightings.
- **Keys:** surrogate keys against V1 legacy IDs. Which IDs users see and type.
- **GPS tracks in DuckLake:** where the catalog lives (Postgres or a DuckDB file), the Parquet layout and partitioning on the droplet's disk, which copy is the source of truth, how the PostGIS copy is kept in sync (and at what level of detail), how the website reads tracks, and how users query them. Measure on track sizes like V1's (there are no track files in `Data/`, so estimate from `TrackT` and the line geometry).
- **Audit log:** compare at least these approaches: history tables with `valid_from` and `valid_to` (the shape dbt snapshots produce), trigger-based change tables, django-pghistory, django-simple-history, and DuckLake time travel for tracks. The result must answer "how has this record changed over time, by hand and by the pipeline?" in one place, keep every edit reversible, and accept a later dbt job without rework.
- **Roles:** how the role model in the spec maps onto Django's groups and permissions, with no custom permission tables unless Django's own cannot express it.
- **Analysis access:** which tables or views are exposed for read-only SQL, and in what form (DuckLake, Parquet exports or Postgres views).

### 3. Write The Schema

- `docs/schema/schema.md`: an ER diagram in Mermaid, and every table with its purpose, columns, types, constraints and indexes (each with the query it serves). Mark which spec requirements each table supports.
- `docs/schema/schema.sql`: runnable DDL for PostgreSQL 18 with PostGIS, with views and materialized views included. Check that it loads into a scratch database. The local Postgres 18 has no PostGIS until Phase 4, so validate the non-spatial parts there, or with DuckDB's Postgres dialect. Say exactly what was and was not checked.
- `docs/schema/ducklake.md`: the track storage design from the decision records, with a diagram of the write path and the read path.
- `docs/schema/audit.md`: the chosen audit design, with worked examples (a hand edit, a pipeline reload and a revert) showing the rows that result.

### 4. Specify The Synthetic Data

Write `docs/schema/synthetic-data-profile.md`. This is what the Phase 4 generator must reproduce: volumes per table (full size for performance testing and a small size for tests), distributions and correlations measured in step 1 (seasonality, species mix, vessel use, group sizes, effort length, and GPS fix rate and speed), realistic tracks along real coastlines, and the edge cases the site must handle. The data must be invented, with no real records copied, while staying statistically close to the real data.

## Exit Checklist

- [ ] `data-profile.md` and `profile_queries.sql`.
- [ ] A decision record for every open question, each one confirmed by Brandon.
- [ ] `schema.md`, a validated `schema.sql`, `ducklake.md` and `audit.md`.
- [ ] `synthetic-data-profile.md`.
- [ ] Every table traces to the spec, and every spec page has the data it needs.
- [ ] Questions logged, STATUS.md updated, the branch pushed, and Brandon asked to approve.
