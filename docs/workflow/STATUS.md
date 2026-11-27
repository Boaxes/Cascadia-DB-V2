# Status

The agent keeps this file current so any session can pick up where the last one stopped.

## Current Phase

Phase 2: Schema And DuckLake, on branch `phase-2-schema`. Every exit checklist item is done and the review items are confirmed (Q-083). Waiting on Brandon's approval.

## Done

- Phase 1 approved 2026-11-26.
- CR-001 accepted 2026-11-27 (versioned records replace Undo): `docs/spec/spec.md`, `mockups/audit.html` and `mockups/edit.html` updated. Phase 1 stays approved.
- **Step 1:** `docs/schema/data-profile.md` and `profile_queries.sql`. Every figure cites a named query. Scripts are in `scratch/profile/`.
- **Step 2:** decision records 001 to 006 in `docs/schema/decisions/`, answered by Brandon (Q-062 to Q-077).
  - Catalogs: two tables.
  - Keys: hashed.
  - Tracks: one `gold.track` row per version holding every GPS point (Q-078), with DuckLake as a copy (Q-082).
  - Audit: versioned rows.
  - SQL page: Parquet of current rows, lines and points by year.
  - Roles: six permissions on Groups.
- **Step 3:**
  - `schema.sql`, `schema.md` (ER diagram, every table and index with the query it serves, page-by-page data check), `ducklake.md` and `audit.md`.
  - `schema.sql` loads into a throwaway PostgreSQL 18.6 cluster with `pg_trgm`, made with `initdb` under `scratch/pgcheck/` (Brandon's service untouched). PostGIS types, the four GiST indexes and `is_on_land()` were stubbed, because PostGIS isn't installed until Phase 4.
  - `scratch/pgcheck/behaviour.sql` checks load, edit, delete with dependents, restore, the guards, track status and the summary views. Its output is in `audit.md`.
  - `scratch/pgcheck/summary_timing.sql` times the summaries on full-size invented rows.
  - Rerun with `bash scratch/pgcheck/check.sh` after starting the cluster: `pg_ctl -D scratch/pgcheck/data -o "-p 55432" start`.
- **Step 4:** `synthetic-data-profile.md`, with full and small sizes, distributions, tracks, photo-ID, edge cases and history scenarios.
- **Review changes (Q-078 to Q-082):**
  - Tracks are one row per version (MultiLineStringM).
  - The docs say "GPS point", not "fix".
  - Bloat pass:
    - `change_source`, `deleted` and track `status` dropped.
    - Four change types on every table.
    - `effort_summary` and `place_name` are plain views.
    - Postgres is the source of truth for tracks, and DuckLake is a copy.

## Waiting on Brandon

- **Approve Phase 2** by adding `Phase 2: Approved 2026-11-27` to the approvals file.
- **Commit the gate and CLAUDE.md edits** on `phase-2-schema` (they are protected, so only Brandon commits them).
- **Edit the V1 line in `CLAUDE.md`** (Sources): change `f4b2a36` to `3a637f1` and `2026-09-29` to `2026-11-21`.
- **Optional, Brandon-only docs:** `phase-5-build.md` (Q-059, one-step build) and the screenshot steps (Q-061).

## Next

- After approval: Phase 3 (Quality Gates) on branch `phase-3-quality`.
- Carry into Phase 4:
  - Load `schema.sql` unchanged into PostGIS and test the stubbed parts.
  - Confirm the DuckLake features in `ducklake.md`, and time a full rebuild of the lake.
  - Re-time `effort_summary` (a plain view) on the droplet.
  - Choose the land outline.
  - Install a recent `gh` with a push token on the server (Q-056).
