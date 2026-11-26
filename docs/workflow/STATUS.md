# Status

The agent keeps this file current so any session can pick up where the last one stopped.

## Current Phase

Phase 1: Spec And Mockup. In progress, step 2 (asking), on branch `phase-1-spec`.

## Done

- Workflow, phase gate and phase docs set up (2026-11-26).
- Branch `phase-1-spec` created (2026-11-26).
- Rounds 1 to 3 of questions asked and logged as Q-001 to Q-012 in `questions-log.md`.
  - Decided: Nothing is public. Map uses MapLibre plus deck.gl. Five roles (Viewer, Editor, Track Manager, Audit Manager, Admin). SQL runs in DuckDB WASM and saved queries go in cookies (text only). Whole-table export covers gold tables only. Records open in an htmx modal. An effort has exactly one GPS track.
- Draft `docs/spec/v1-inventory.md`, now marked stale (see below).

## Next

- Once `V1/` holds current main, redo `v1-inventory.md` against it. Pay particular attention to `datahealth` (Django admin site, `access.py`, `setup_access`), `feedback`, the Settings, Server and pipeline pages, and the track file manager. Then re-ask for confirmation, and re-check Q-010 and Q-011.
- Then continue asking: the permission table for the five roles, navigation and landing page, each page, tracks settings, photo-ID catalogs, audit log view, and extra features.

## Waiting On Brandon

- `V1/` is a stale copy: it holds `f4b2a36` (2026-09-29), while `Boaxes/Cascadia-DB` main is at `3a637f1` (2026-11-21), 83 commits ahead. `V1/` and `CLAUDE.md` are Brandon-only, so he needs to refresh `V1/` from main and update the commit and date in CLAUDE.md (Sources, V1 bullet).
