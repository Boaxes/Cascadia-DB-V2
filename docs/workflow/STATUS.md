# Status

The agent keeps this file current so any session can pick up where the last one stopped.

## Current Phase

Phase 1: Spec And Mockup. In progress, step 2 (asking), on branch `phase-1-spec`.

## Done

- Workflow, phase gate and phase docs set up (2026-11-26).
- Branch `phase-1-spec` created (2026-11-26).
- `V1/` refreshed by Brandon to `Boaxes/Cascadia-DB` main `3a637f1` (2026-11-21). The first draft of the inventory came from a stale copy (`f4b2a36`) and was redone.
- `docs/spec/v1-inventory.md` redone against `3a637f1` and confirmed (Q-017).
- Every earlier decision re-checked against current V1. Rounds 1 to 6 are logged as Q-001 to Q-024 in `questions-log.md`. Decided:
  - **Access:** Nothing public. Five roles (Viewer, Editor, Track Manager, Audit Manager, Admin), assigned by role only. Every role can export and use SQL.
  - **Map:** MapLibre plus deck.gl.
  - **Navigation:** Sidebar groups Survey, Photo-ID, Data (Export, SQL) and Manage, with Feedback and Settings at the bottom. Explore is the landing page.
  - **Records:** An htmx modal. One GPS track per effort.
  - **Export and SQL:** Whole-table export covers gold tables only. SQL runs in DuckDB WASM on its own page, with saved queries in cookies, and can send a query to the Export stack.
  - **Audit:** History shows audit log changes only. No DB167 write-back, but audit entries stay complete for a later job.
  - **Admin tools:** Feedback and the Server page stay. The Data Pipeline page and read-only record admin are dropped.

## Next

- Continue asking. Remaining topics:
  - (Done in round 6: permission table Q-021, Research Group default Q-022, years Q-023, page size Q-024.)
  - Each page in detail: purpose, columns, filters and defaults, sorting, paging, actions, empty and error states.
  - Tracks: the single component and its settings.
  - Photo-ID catalogs: pages, and how MnID's `Sharing_Status` (Public, Private, blank) affects what users see.
  - The Audit Log page.
  - Proposed extra features.
- Then write `docs/spec/spec.md`, then the mockups.

## Waiting On Brandon

- Commit the refreshed `V1/` on `phase-1-spec` (the gate stops the agent from doing it).
- Edit the V1 line in `CLAUDE.md` (Sources section): change `f4b2a36` to `3a637f1` and `2026-09-29` to `2026-11-21`.
