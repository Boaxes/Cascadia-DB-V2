# Questions Log

Every question put to Brandon and his answer, in order, so no decision lives only in a chat. Add an entry as soon as a question is answered.

Format:

```
### Q-001: Short Title (Phase 1)
Asked: 2026-11-27
Options: A (recommended), B, C
Answer: B, because ...
Affects: spec.md SIGHT-02, mockups/sightings.html
```

## Questions


### Q-001: Permission Model (Phase 1)
Asked: 2026-11-26
Options: A Viewer/Editor/Admin (recommended), B Viewer and Editor, C One role
Answer: Other: "More roles. What's in V1 on Django Admin should be a role above." V1's `/admin/` panel (admintools: dashboard, track-file fixes, audit log with Undo) becomes its own role above the editing roles. Exact role list to be confirmed in round 2 (Q-005).
Affects: spec.md Users and Permissions

### Q-002: Public Access (Phase 1)
Asked: 2026-11-26
Options: A Nothing public (recommended), B Public about page
Answer: A. Every page, including the landing page, needs a login.
Affects: spec.md Users and Permissions, NAV

### Q-003: Map Library (Phase 1)
Asked: 2026-11-26
Options: A MapLibre now, deck.gl later (recommended), B MapLibre only, C MapLibre plus deck.gl
Answer: C. MapLibre GL JS plus deck.gl from the start.
Affects: spec.md Map Behaviour, Tracks

### Q-004: Analysis Features (Phase 1)
Asked: 2026-11-26
Options (multi-select): Read-only SQL page, Parquet and CSV downloads, Saved queries, Notebook starter
Answer: Other: The Export page can export entire tables, both raw and gold, as one option. A second option is sending a SQL query to the Export page. Users can save SQL queries, stored as cookies, with no sharing logic. Keep the code and implementation simple. Where the SQL runs and what "raw" means in V2 to be confirmed in round 2 (Q-006, Q-007).
Affects: spec.md Exports, Analysis, mockups/export.html

### Q-005: Role List (Phase 1)
Asked: 2026-11-26
Options: A Four roles: Viewer, Editor, Data Manager, Admin (recommended); B Three roles: Viewer, Editor, Admin; C Five roles: Viewer, Editor, Track Manager, Audit Manager, Admin
Answer: C. Five roles. Track Manager takes V1's track-file fixes, Audit Manager takes V1's audit log and Undo. The full permission table is to be confirmed in a later round.
Affects: spec.md Users and Permissions

### Q-006: Where SQL Runs (Phase 1)
Asked: 2026-11-26
Options: A Server DuckDB (recommended), B Browser DuckDB WASM, C Server Postgres
Answer: B, DuckDB WASM in the browser. Clarification from Brandon: "low JS" means little custom JavaScript logic written for the Django site. Established third-party libraries (DuckDB WASM, MapLibre, deck.gl) are fine.
Affects: spec.md Analysis, Exports, mockups/export.html

### Q-007: Raw Tables (Phase 1)
Asked: 2026-11-26
Options: A Source tables as Parquet (recommended), B Gold only for now, C Original GPS files only
Answer: B. Whole-table export covers gold tables only for now. Raw export waits for the dbt work, and the spec only reserves a place for it. This narrows Q-004.
Affects: spec.md Exports, Out Of Scope

### Q-008: V1 Inventory Proposals (Phase 1)
Asked: 2026-11-26
Options: A Confirm all (recommended), B Confirm with changes
Answer: Not yet confirmed. Brandon corrected the effort detail row: an effort has exactly one GPS track. Finding: the V1 snapshot has 30 efforts with 2 or 3 track records (duplicate rows for the same file, or a handheld GPX file and a tablet file for the same day). V2 treats one track per effort as the rule and these as data problems. Re-asked with the correction as Q-009.
Affects: v1-inventory.md row 4, spec.md Tracks, Phase 2 schema (one track per effort)

### Q-009: V1 Inventory Proposals, Corrected (Phase 1)
Asked: 2026-11-26
Options: A Confirm all (recommended), B Confirm with changes
Answer: A, but void. Brandon then pointed out that the V1 admin dashboard was removed a while ago. Check: `V1/` is a copy of `f4b2a36` (2026-09-29), while `Boaxes/Cascadia-DB` main is at `3a637f1` (2026-11-21), 83 commits and 300 files ahead. Among the changes: `admintools` was replaced by `datahealth` (which uses Django's admin site and adds an access setup), plus new `feedback` app, Settings page, Server page, pipeline page and track file manager. The inventory must be redone against current main and confirmed again.
Affects: v1-inventory.md (all rows)

### Q-010: How A Record Opens (Phase 1)
Asked: 2026-11-26
Options: A htmx side panel (recommended), B Plain pages, C Modal with htmx
Answer: C. A modal, rebuilt with htmx and the native `<dialog>` element. Whether this still holds against current V1 is to be checked after the inventory is redone.
Affects: spec.md Cross-Cutting Behaviour, every list and map mockup

### Q-011: V1 Admin Dashboard (Phase 1)
Asked: 2026-11-26
Options: A Drop it (recommended), B Small overview, C Keep as in V1
Answer: None. Brandon noted the dashboard was removed a while ago, which revealed the stale V1 copy (see Q-009). To be re-asked against current main if still relevant.
Affects: v1-inventory.md

### Q-012: Saved SQL Storage (Phase 1)
Asked: 2026-11-26
Options: A localStorage (recommended), B Cookies
Answer: B, cookies. Only the query text is saved, never results, so it fits within the cookie size limit.
Affects: spec.md Analysis, mockups/export.html

### Re-Check Against Current V1 (Phase 1)
2026-11-26: `V1/` refreshed by Brandon to `3a637f1`. Every earlier decision was re-checked against current V1. Q-002, Q-003, Q-004, Q-006, Q-007, Q-010 and Q-012 stand. Q-001 and Q-005 were asked again as Q-013, because current V1 already has four roles. Q-011 is answered by current V1 (the Cascadia Admin home is now three link cards) and is folded into the inventory confirmation. The inventory was redone (Q-008, Q-009).

### Q-013: Role Model Against Current V1 (Phase 1)
Asked: 2026-11-26
Options: A Five roles mapped onto V1 (recommended), B V1's four roles, fixed
Answer: A. Viewer (read). Editor (also edit and delete efforts and sightings). Track Manager (Editor plus the Track File Manager). Audit Manager (Editor plus the Audit Log and Undo). Admin (everything plus users and roles). Track Manager and Audit Manager sit side by side, and one person can hold both. Access comes from roles only, with no per-user permission grants. Supersedes Q-001 and Q-005.
Affects: spec.md Users and Permissions

### Q-014: Who Can Export (Phase 1)
Asked: 2026-11-26
Options: A Every role (recommended), B Editor and up, C Data roles only
Answer: A. Every role, Viewer included, can export and use the SQL page.
Affects: spec.md Users and Permissions, Exports

### Q-015: DB167 Write-Back (Phase 1)
Asked: 2026-11-26
Options: A Drop, keep entries ready (recommended), B Keep as in V1, C Drop entirely
Answer: A. V2 has no DB167 state and no T-SQL migration script. Audit entries hold the table, key, old and new values so a later job can write back.
Affects: spec.md Audit Log, Out Of Scope; Phase 2 audit design

### Q-016: Other V1 Admin Tools (Phase 1)
Asked: 2026-11-26
Options (multi-select): Feedback to GitHub, Server page, Data Pipeline page, Read-only record admin
Answer: Feedback to GitHub and Server page stay. Data Pipeline page and the Django Admin read-only record pages are dropped. Feedback pictures move behind the login (Q-002). Which role sees the Server page goes into the permission table, to be confirmed.
Affects: spec.md Pages, v1-inventory.md rows 19, 26, 27, 28
