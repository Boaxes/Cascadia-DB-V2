# Status

The agent keeps this file current so any session can pick up where the last one stopped.

## Current Phase

Phase 1: Spec And Mockup. In progress, step 2 (asking), on branch `phase-1-spec`.

## Done

- Workflow, phase gate and phase docs set up (2026-11-26).
- Branch `phase-1-spec` created (2026-11-26).
- `V1/` refreshed by Brandon to `Boaxes/Cascadia-DB` main `3a637f1` (2026-11-21). The first draft of the inventory came from a stale copy (`f4b2a36`) and was redone.
- `docs/spec/v1-inventory.md` redone against `3a637f1` and confirmed (Q-017).
- Every earlier decision re-checked against current V1. Rounds 1 to 14 are logged as Q-001 to Q-055 in `questions-log.md`. Decided:
  - **Access:** Nothing public. Five roles (Viewer, Editor, Track Manager, Audit Manager, Admin), assigned by role only. Every role can export and use SQL.
  - **Map:** MapLibre plus deck.gl. Basemaps as V1. Explore keeps Fullscreen, Screenshot and the Clustering toggle; Measure is dropped.
  - **Tracks:** One component. Settings (cookie, with per-map toggles): points, gaps, timeline events, direction arrows; gap rules by time, distance and speed; gap style dashed, faint line or nothing. One colour from the colour profile; suspect tracks red and dashed. Detail levels as V1; the site reads points from PostGIS, DuckLake is the source of truth.
  - **Navigation:** Sidebar groups Survey, Photo-ID, Data (Export, SQL) and Manage, with Feedback and Settings at the bottom. Explore is the landing page.
  - **Records:** An htmx modal. One GPS track per effort.
  - **Export and SQL:** Whole-table export covers gold tables only. SQL runs in DuckDB WASM on its own page, with saved queries in cookies, and can send a query to the Export stack.
  - **Audit:** History shows audit log changes only. No DB167 write-back, but audit entries stay complete for a later job.
  - **Photo-ID:** One combined Individuals list (species filter) and an Individual page; sidebar Photo-ID group has one Individuals link. Everyone sees private records; sharing status is a column, filter and export column. Catalog data is read only on the site (changes only through dbt); History shows pipeline changes. Photos are placeholder whale icons in a random colour per render; real photos later (OBIS-SEAMAP lead).
  - **Extras:** Global search over IDs and names with fuzzy matching (`pg_trgm`), and an Individual Filter on Explore and Sightings.
  - **Admin tools:** Feedback and the Server page stay. The Data Pipeline page and read-only record admin are dropped.

## Next

- `docs/spec/spec.md` written (step 3): 158 requirements with IDs and checks, sections 1 to 7, no open assumptions (Q-001 to Q-058).
- Step 4: build the static HTML mockups in `mockups/` (one file per page, shared `style.css`), preview each with the `mockups` launch configuration, then iterate with Brandon.

## Waiting On Brandon

- Commit the refreshed `V1/` on `phase-1-spec` (the gate stops the agent from doing it).
- Update `docs/workflow/phase-5-build.md` so the build is one step (Q-059), if you want the doc to match.
- Edit the V1 line in `CLAUDE.md` (Sources section): change `f4b2a36` to `3a637f1` and `2026-09-29` to `2026-11-21`.
