# Status

The agent keeps this file current so any session can pick up where the last one stopped.

## Current Phase

Phase 4: Scaffolding, on branch `phase-4-scaffolding`. Starting: plan and first questions.

## Done

- Phase 1 approved 2026-11-26. Phases 2 and 3 approved 2026-11-27 (Phase 3 assumptions stand, Q-102).
- **Phase 3** (Q-084 to Q-101):
  - `quality-gates.md`: Claude hooks after each save and before done (blocks until green), the commit check, and GitHub on every push. Brandon's rules: one comment per file, helpers used 3 times, no block of 5+ lines repeated 3 times, a Haiku review of each code-changing turn. mypy (moderate), 85% coverage with every spec ID tested, query counts, Playwright smoke tests.
  - `style-guide.md`: five apps by sidebar group, plain function views, JavaScript where simpler than htmx.
  - `definition-of-done.md`.

### Phase 2 Record

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

- **Commit the approvals file** (Phase 3 line).
- **Edit the V1 line in `CLAUDE.md`** (Sources): change `f4b2a36` to `3a637f1` and `2026-09-29` to `2026-11-21`.
- **Optional, Brandon-only docs:** `phase-5-build.md` (Q-059, one-step build) and the screenshot steps (Q-061).

## Next

- Carry into Phase 4:
  - Wire in every gate in `docs/quality/quality-gates.md`, Claude hooks first.
  - Load `schema.sql` unchanged into PostGIS and test the stubbed parts.
  - Confirm the DuckLake features in `ducklake.md`, and time a full rebuild of the lake.
  - Re-time `effort_summary` (a plain view) on the droplet.
  - Choose the land outline.
  - Install a recent `gh` with a push token on the server (Q-056).
