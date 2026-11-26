# Status

The agent keeps this file current so any session can pick up where the last one stopped.

## Current Phase

Phase 1: Spec And Mockup. Complete and waiting for Brandon's approval, on branch `phase-1-spec`.

## Done

- Workflow, phase gate and phase docs set up (2026-11-26).
- Branch `phase-1-spec` created (2026-11-26).
- `V1/` refreshed by Brandon to `Boaxes/Cascadia-DB` main `3a637f1` (2026-11-21). The first draft of the inventory came from a stale copy (`f4b2a36`) and was redone.
- `docs/spec/v1-inventory.md` redone against `3a637f1` and confirmed (Q-017).
- `docs/spec/spec.md`: 159 requirements with IDs and checks, no open assumptions.
- `mockups/`: 19 pages plus `index.html` (the list of pages and URL variants), shared `style.css`, `icons.svg`, `sidebar.js`, `filters.js` and three map pictures. Each page checked in the preview at 1440 px and 390 px. Brandon says they look fine for now.
- Reference screenshots skipped by Brandon's decision (Q-061): the mockups are the visual reference, and drift in the build is acceptable because it is refined through feedback.
- Every question logged, Q-001 to Q-061. Decided:
  - **Name:** The site is Unified DB (Q-060).
  - **Access:** Nothing public. Five roles (Viewer, Editor, Track Manager, Audit Manager, Admin), assigned by role only. Every role can export and use SQL.
  - **Map:** MapLibre plus deck.gl. Basemaps as V1. Explore keeps Fullscreen, Screenshot and the Clustering toggle; Measure is dropped.
  - **Tracks:** One component. Settings (cookie, with per-map toggles): points, timeline events, direction arrows, no-track path (on by default); gap rules by time, distance and speed; gap style dashed, faint line or nothing. One colour from the colour profile; suspect tracks red and dashed. Detail levels as V1; the site reads points from PostGIS, DuckLake is the source of truth.
  - **Navigation:** Sidebar groups Survey, Photo-ID, Data (Export, SQL) and Manage, with Feedback and Settings at the bottom. Explore is the landing page. Global fuzzy search at the top.
  - **Records:** An htmx modal. One GPS track per effort.
  - **Export and SQL:** Whole-table export covers gold tables only, with Parquet added. SQL runs in DuckDB WASM on its own page, with saved queries in cookies, and sends queries to the Export stack.
  - **Audit:** One log for people and the pipeline. Undo deletes the entry; pipeline entries cannot be undone. History explains the current state. No DB167 write-back, but entries stay complete for a later job.
  - **Photo-ID:** One combined Individuals list and an Individual page. Catalog data is read only (changes only through dbt). Everyone sees private records. Photos are random-colour whale icons; real photos later (OBIS-SEAMAP lead).
  - **Admin tools:** Track File Manager kept. Feedback goes to GitHub with pictures attached by `gh` (the site stores none). Server page in the site layout. Users through Django Admin. The Data Pipeline page and read-only record admin are dropped.
  - **Workflow:** Phase 5 is one step, not one branch per feature (Q-059).

## Next

- After Brandon approves Phase 1: Phase 2 (Schema And DuckLake) on a new branch `phase-2-schema`, starting with the data profile.
- Carry into Phase 2: a time on every GPS point (TRACK-06), the PostGIS copy of DuckLake (MAP-06), Parquet refresh for SQL (SQL-01), and complete audit entries (HIST-02). Carry into Phase 4: a recent `gh` and push token on the server (Q-056), and the deploy path.

## Waiting On Brandon

- Approve Phase 1 by adding the line `Phase 1: Approved <date>` to the approvals file in `docs/workflow/` (Brandon-only).
- Commit the refreshed `V1/` on `phase-1-spec` (the gate stops the agent from doing it).
- Edit the V1 line in `CLAUDE.md` (Sources section): change `f4b2a36` to `3a637f1` and `2026-09-29` to `2026-11-21`.
- Optional, Brandon-only docs: `phase-5-build.md` for the one-step build (Q-059), and the screenshot steps in `phase-1-spec-and-mockup.md` and `phase-5-build.md` (Q-061).
