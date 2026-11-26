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

### Q-017: Redone V1 Inventory (Phase 1)
Asked: 2026-11-26
Options: A Confirm all (recommended), B Confirm with changes
Answer: A. All 28 rows of `v1-inventory.md` (at `3a637f1`) confirmed, including dropping the Cascadia Admin home (closes Q-011).
Affects: v1-inventory.md, spec.md

### Q-018: Record History Without Raw Data (Phase 1)
Asked: 2026-11-26
Options: A Audit log only (recommended), B Keep source values
Answer: A. A record's History shows only what the audit log holds: each change by a person or the pipeline, with who, when, why, and old and new values. V1's "Original Database" and "After Cleaning" steps are not carried over.
Affects: spec.md Audit Log (user-facing), record detail pages

### Q-019: Sidebar Layout (Phase 1)
Asked: 2026-11-26
Options: A As proposed (recommended), B SQL as its own link, C Catalogs under Survey
Answer: B. Top: logo and site name. Survey: Explore, Efforts, Sightings. Photo-ID: Humpback Whales (MnID), Blue Whales (Bm), Gray Whales (ErId). Data: Export, SQL. Manage: Track File Manager (Track Manager), Audit Log (Audit Manager), Users (Admin), Server (Admin). Bottom: Feedback, Settings, user name with Sign Out. Links show only to roles that can use them. The SQL page can send a query to the Export stack (Q-004).
Affects: spec.md Information Architecture, every mockup

### Q-020: Landing Page (Phase 1)
Asked: 2026-11-26
Options: A Explore (recommended), B Sightings list, C New home page
Answer: A. Explore opens after sign-in, and `/` goes to Explore.
Affects: spec.md NAV

### Q-021: Permission Table (Phase 1)
Asked: 2026-11-26
Options: A As in the table (recommended), B Audit Log readable by all, C Server for Audit Manager
Answer: A.

| Action | Viewer | Editor | Track Manager | Audit Manager | Admin |
|---|---|---|---|---|---|
| Browse Explore, Efforts, Sightings, Photo-ID, record History | Yes | Yes | Yes | Yes | Yes |
| Export and SQL | Yes | Yes | Yes | Yes | Yes |
| Feedback, Settings, change own password | Yes | Yes | Yes | Yes | Yes |
| Edit and delete efforts and sightings | | Yes | Yes | Yes | Yes |
| Track File Manager and the track buttons on effort pages | | | Yes | | Yes |
| Audit Log page, and Undo of any change (tracks included) | | | | Yes | Yes |
| Users and roles | | | | | Yes |
| Server page | | | | | Yes |

Changing one's own password moves out of the Django Admin. Photo-ID catalog editing is decided with the catalog pages.
Affects: spec.md Users and Permissions

### Q-022: Research Group Default (Phase 1)
Asked: 2026-11-26
Options: A CRC as V1 (recommended), B All groups, C Per user in Settings
Answer: A, changed: CRC is the default, but without V1's special UI (the always-visible chip and separate All box). Research Group is an ordinary filter like Vessel, with CRC selected in it by default.
Affects: spec.md filters, Explore, Efforts, Sightings mockups

### Q-023: Default Years (Phase 1)
Asked: 2026-11-26
Options: A All years (recommended), B Explore last 5 years, C Current year
Answer: A. Explore, Efforts and Sightings show all years by default.
Affects: spec.md filters

### Q-024: Rows Per Page (Phase 1)
Asked: 2026-11-26
Options: A 50 with picker (recommended), B 50, no picker, C 100 with picker
Answer: B. Efforts and Sightings show 50 rows per page, with no page-size picker.
Affects: spec.md Efforts and Sightings lists

### Q-025: Track Display Settings (Phase 1)
Asked: 2026-11-26
Options (multi-select): Show points, Gaps as dashed lines, Timeline events, Direction arrows
Answer: All four are user settings. In addition, gaps need stronger controls than one toggle: the user controls what counts as a gap and what a gap renders as. Settings are stored per user in a cookie. Gap details asked as Q-029 and Q-030.
Affects: spec.md Track Display Settings, mockups/settings.html, every map mockup

### Q-026: Track Colour (Phase 1)
Asked: 2026-11-26
Options: A One colour (recommended), B One or by vessel, C One, vessel, or time
Answer: A. One track colour, set by the colour profile. A suspect track (implied speed over 40 kn) is always red and dashed.
Affects: spec.md Track Display Settings

### Q-027: Where Track Settings Live (Phase 1)
Asked: 2026-11-26
Options: A Cookie plus map toggles (recommended), B Cookie only, C User account in the database
Answer: A. The Settings page saves defaults in a cookie. Each map's layer panel can flip a setting for that view only without changing the saved default.
Affects: spec.md Track Display Settings, Map Behaviour

### Q-028: Track Level Of Detail (Phase 1)
Asked: 2026-11-26
Options: A Simplified on Explore, full points on detail views from DuckLake (recommended), B As V1, C Full points everywhere
Answer: B. Explore draws lines simplified to about 550 m, effort and sighting detail draw the stored line (about 11 m), and only the Track File Manager shows full points. Correction from Brandon: the website reads GPS points from PostGIS, which holds a copy; DuckLake is the source of truth (V2Spec). Option A wrongly had the site reading points from DuckLake. The storage design is Phase 2.
Affects: spec.md Map Behaviour, Tracks; Phase 2 DuckLake and PostGIS design
