# Status

The agent keeps this file current so any session can pick up where the last one stopped.

## Current Phase

Phase 2: Schema And DuckLake, on branch `phase-2-schema`. Phase 1 approved 2026-11-26.

## Done

- Phase 1 complete and approved (spec, inventory, mockups, Q-001 to Q-061).
- Branch `phase-2-schema` created from `phase-1-spec` (2026-11-27).
- Step 1: `docs/schema/data-profile.md` and `docs/schema/profile_queries.sql`. Every figure cites a named query. Working scripts are in `scratch/profile/` (`run_queries.py`, `summarize.py`, `track_size.py`).
- Step 2: six decision records in `docs/schema/decisions/`, each answered by Brandon (Q-062 to Q-077):
  - **001 Catalogs:** two tables, `individual` (other IDs and `extra` in jsonb) and `identification` (survey and MnID records together), plus `individual_id` and `extra` on `sample`.
  - **002 Keys:** hashed keys as V1, with the DB167 ID as `legacy_id` for display and URLs.
  - **003 Tracks:**
    - DuckLake (catalog in a Postgres schema, `track_point` partitioned by year) is the source of truth.
    - PostGIS holds every point plus 11 m and 550 m lines whose vertices carry times and step maxima.
    - Each write rebuilds the track in PostGIS, and a nightly check catches drift.
    - pg_duckdb and pg_ducklake can't run PostGIS over DuckLake.
  - **004 Audit:** versioned rows (`valid_from`, `valid_to`, who, why, `change_id`, `deleted`), all versions in one table per record type with a `_current` view.
    - Restore inserts a copy of any version. Nothing is deleted.
    - The pipeline loads incrementally and only writes first versions of new records.
  - **005 SQL page:** Parquet of current rows, 11 m track lines and points by year, served with range requests.
  - **006 Roles:** six custom permissions on the five Groups, set from code.
- CR-001 raised: versioned rows change AUD-02, AUD-04, AUD-05, HIST-01 to HIST-03, EDIT-06 and TFM-08 in the frozen spec.

## Next

- Step 3:
  - `schema.md` (Mermaid ER diagram and every table, each index with the query it serves).
  - `schema.sql` (validated on local Postgres 18 for the non-spatial parts).
  - `ducklake.md` (write and read paths).
  - `audit.md` (worked examples: a hand edit, a pipeline load, a restore).
- Step 4: `synthetic-data-profile.md`.
- Check that every spec page has the data it needs. Then ask Brandon to approve Phase 2.

## Waiting on Brandon

- CR-001: accept or reject. Suggested: collect every spec change from Phase 2 and reopen Phase 1 once, near the end of Phase 2.
- Edit the V1 line in `CLAUDE.md` (Sources): change `f4b2a36` to `3a637f1` and `2026-09-29` to `2026-11-21`.
- Optional, Brandon-only docs: `phase-5-build.md` for the one-step build (Q-059), and the screenshot steps (Q-061).
