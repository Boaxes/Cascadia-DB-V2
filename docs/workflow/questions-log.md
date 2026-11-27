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

### Q-029: What Counts As A Gap (Phase 1)
Asked: 2026-11-26
Options: A Time, user minutes (recommended), B Time or distance, C Time, distance, speed
Answer: C. The user sets three gap rules, and any one met makes a gap: minutes of GPS silence, a jump in metres between consecutive fixes, and an implied speed in knots between consecutive fixes. The stored line keeps a time on every vertex so gaps can be redrawn per user (Phase 2).
Assumption, to confirm at the spec review: defaults are 30 minutes, distance off, speed off (V1 behaviour). Allowed ranges are 1 to 240 minutes, 50 to 50,000 m, and 5 to 100 kn.
Affects: spec.md Track Display Settings; Phase 2 track geometry

### Q-030: Gap Render Styles (Phase 1)
Asked: 2026-11-26
Options (multi-select): Dashed line, Dotted line, Faint straight line, Nothing
Answer: Dashed line, Faint straight line, Nothing. The user picks one; Dashed line is the default (V1 behaviour). No dotted style.
Affects: spec.md Track Display Settings, mockups/settings.html

### Q-031: Explore Map Tools (Phase 1)
Asked: 2026-11-26
Options (multi-select): Measure, Fullscreen, Screenshot, Clustering toggle
Answer: Fullscreen, Screenshot and the Clustering toggle stay. Measure is dropped. The draw-area filter stays as part of the filter panel (Q-017).
Affects: spec.md Map Behaviour, mockups/explore.html

### Q-032: Basemaps (Phase 1)
Asked: 2026-11-26
Options: A Same as V1 (recommended), B V1 plus NOAA charts, C Satellite and Ocean
Answer: A. Satellite (Esri World Imagery, default), Map (OpenStreetMap), Ocean (Esri World Ocean Base), plus the Place Names overlay.
Affects: spec.md Map Behaviour

### Q-033: Catalog Pages (Phase 1)
Asked: 2026-11-26
Options: A Per-catalog list and Individual page (recommended), B One combined list, C Individual page only
Answer: B. One combined Individuals list across all photo-ID catalogs (MnID now, Bm and ErId later) with a species filter, plus an Individual page. This changes the sidebar from Q-019: the Photo-ID group holds one Individuals link instead of one link per catalog.
Affects: spec.md Information Architecture, Pages; mockups/individuals.html, mockups/individual.html

### Q-034: Private Sharing Status (Phase 1)
Asked: 2026-11-26
Options: A All see, status shown (recommended), B Hidden from exports, C Some roles only
Answer: A. Every role sees every record. Sharing status is a column, a filter and an export column.
Affects: spec.md Photo-ID pages, Exports

### Q-035: Editing Catalogs (Phase 1)
Asked: 2026-11-26
Options: A Read only (recommended), B Editor and up, C New Catalog Editor role
Answer: Editing and history work exactly as for efforts and sightings: Editor and above edit and delete through the same two-step form, every change goes through the audit log, and the record shows its History. "Don't make this overly complicated." Which catalog fields are editable is settled with the page details.
Affects: spec.md Users and Permissions, Photo-ID pages

### Q-036: Photo-ID Images (Phase 1)
Asked: 2026-11-26, in three steps
Options (first): A No images, link to HappyWhale (recommended), B Store and show photos
Answer (first): Check whether HappyWhale has an API for pulling images. Cascadia's own images are not supported for now.
Finding: Happywhale has no documented public API. The unofficial CLI `open-oceans/happywhale` (last updated 2023-11) used undocumented endpoints on `critterspot.happywhale.com`, all behind a Happywhale username and password login. MnID holds 112,613 HappyWhale media IDs and 121,730 encounter links, with mixed licences (public domain, CC variants, copyright, 5,510 PRIVATE).
Answer (second): Check whether the API would work under load or hit rate limits.
Finding: `critterspot.happywhale.com` no longer resolves (DNS: non-existent domain); `happywhale.com` itself answers. No working API exists to test. No load test was run against Happywhale.
Answer (final): For now, every place a photo would go shows a whale icon in a random colour, generated on each render and never stored in the database. Brandon notes Happywhale says its images are held at OBIS-SEAMAP (https://seamap.env.duke.edu/), a lead for adding real photos later.
Assumption, to confirm at the spec review: the HappyWhale encounter link stored on MnID records is shown as a plain link field on the record, since it is part of the data.
Affects: spec.md Photo-ID pages, mockups/individual.html, Out Of Scope (real photos)

### Q-037: Explore Results Panel (Phase 1)
Asked: 2026-11-26
Options: A As V1 (recommended), B Paged panel, C No panel
Answer: A. The panel shows the first 300 sightings or efforts, "Showing the first 300 of N" beyond that, an Open As A List link, and Add To Export.
Affects: spec.md Explore, mockups/explore.html

### Q-038: Efforts And Sightings Columns (Phase 1)
Asked: 2026-11-26
Options: A Same columns, all sortable (recommended), B Exactly as V1, C Different columns
Answer: A. Efforts: Date, Effort, Vessel, Locality, Survey Type, Track, Distance (nm), Sightings. Sightings: Date, Time, Sighting, Species, Group Size, Min–Max, Vessel, Position, Effort. Every column sorts; vessel sorts by name on both; default newest first.
Affects: spec.md Efforts, Sightings; mockups/efforts.html, mockups/sightings.html

### Q-039: Individuals List (Phase 1)
Asked: 2026-11-26
Options: A As proposed (recommended), B Without Other IDs, C Different
Answer: A. Columns: ID, Species, Other IDs (shortened), Colour Category, Sex (genetic where known, otherwise behavioural), First Seen, Last Seen, Sightings, Dead. Filters: species, one search box for any ID, alias or retired ID, years seen, region seen, dead. Default sort Last Seen newest first; every column sorts; 50 rows per page with no picker.
Affects: spec.md Individuals, mockups/individuals.html

### Q-040: Individual Page (Phase 1)
Asked: 2026-11-26
Options: A As proposed (recommended), B Without the map, C Different
Answer: A. Opens in the modal. Sections in order: header (ID, species, random-colour whale icon, Edit, Delete and History for Editor and above); IDs card (cross-catalog IDs, aliases, retired IDs); Summary (sex, colour category, first and last seen, sightings count, dead with date); map of every position seen; Sightings table (date, region, locality, contributor, research group, sharing status, quality, HappyWhale link; 50 per page, newest first); Samples table; Survey Sightings where the whale was identified, each opening the sighting.
Affects: spec.md Individual, mockups/individual.html

### Q-041: Whole Gold Tables On Export (Phase 1)
Asked: 2026-11-26
Options: A Whole Tables card plus Parquet (recommended), B Card with V1 formats, C On the SQL page
Answer: A. The Export page gets a Whole Tables card listing every gold table; each ticked table becomes one more sheet in the download. Parquet (zip) joins V1's formats (XLSX, CSV zip, GeoJSON zip, GPX, GeoPackage).
Affects: spec.md Exports, mockups/export.html

### Q-042: SQL Result To Download (Phase 1)
Asked: 2026-11-26
Options: A Send To Export (recommended), B Both, C SQL page only
Answer: A. "Send To Export" adds the named SQL text to the stack. When the file is built, the server re-runs it in a read-only DuckDB over the same Parquet files, with a time limit, and the result is its own sheet. The SQL page has no direct download.
Affects: spec.md Analysis, Exports; mockups/sql.html, mockups/export.html

### Q-043: Settings Page (Phase 1)
Asked: 2026-11-26
Options: A All in Settings (recommended), B Password in user menu
Answer: A. Settings holds Colour Profile, track display defaults (Show Points, Timeline Events, Direction Arrows, the three gap rules, Gap Style) and Change Password. Everything but the password is stored in a cookie.
Affects: spec.md Settings, mockups/settings.html

### Q-044: What Undo Does (Phase 1)
Asked: 2026-11-26
Options: A Add a reversing entry (recommended), B As V1: delete it
Answer: B. Undo deletes the entry fully, as in V1, so the log lists only changes in effect. Clarification from Brandon: V2Spec's "over time" means a record's History explains its current state in order (pipeline changes, then user edits, and so on). It does not mean keeping undone changes.
Affects: spec.md Audit Log; Phase 2 audit design

### Q-045: Audit Log Page (Phase 1)
Asked: 2026-11-26
Options: A As proposed (recommended), B Keep fit-to-window
Answer: A. Filters: Record (type and number), Who (each person, plus Pipeline), Change type, date range. Columns: When, Who, Change, Record, What Changed, Note. 50 per page with no picker; V1's row-measuring JS and the DB167 status are dropped. Each entry opens in the modal with Before/After, Removed With It, and Undo for Audit Manager and Admin.
Affects: spec.md Audit Log, mockups/audit.html

### Q-046: Undoing Pipeline Changes (Phase 1)
Asked: 2026-11-26
Options: A View only (recommended), B Undoable
Answer: A. Pipeline entries can be viewed but not undone. The entry says to change the pipeline rule to reverse it.
Affects: spec.md Audit Log

### Q-047: Users Page (Phase 1)
Asked: 2026-11-26
Options: A Django Admin (recommended), B New site page
Answer: A. Admins manage users in Django Admin's user pages, stripped down and styled like the site: list users with roles, add a user, set roles (one person may hold several), set a password, deactivate. The sidebar's Users link opens it.
Affects: spec.md Users and Permissions

### Q-048: Server Page Placement (Phase 1)
Asked: 2026-11-26
Options: A Site layout (recommended), B Django Admin
Answer: A. V1's Server content (event console with Advanced toggle, 24-hour CPU, memory and disk graph, facts, 5-second refresh) moves into the site's own layout under Manage.
Affects: spec.md Server, mockups/server.html

### Q-049: Editing Photo-ID Catalogs (Phase 1)
Asked: 2026-11-26
Options: A Both record kinds (recommended), B Individual only, C Catalog sightings only
Answer: None of them. Photo-ID catalog data (MnID, Bm, ErId) cannot be edited on the site at all; it changes only through dbt transformations. This supersedes Q-035 and removes Edit and Delete from the Individual page header (Q-040). History on catalog records still shows pipeline changes, read only.
Affects: spec.md Users and Permissions, Individual page; mockups/individual.html

### Q-050: Empty And Error States (Phase 1)
Asked: 2026-11-26
Options: A This standard (recommended), B 403 without the role
Answer: A. No rows: "No [Efforts] match these filters." with Reset Filters. Map data failure: notice "Could not load the map data." with Try Again. Not found: 404 "No [Effort] with ID [N]." with a link to the list. No permission: 403 "This page needs the [Track Manager] role." with a link home. Form error: each bad field outlined with its reason, nothing saved. Server error: 500 "Something went wrong. It has been logged.", recorded in the Server log.
Affects: spec.md Cross-Cutting Behaviour, every page

### Q-051: Feedback Areas (Phase 1)
Asked: 2026-11-26
Options: A V2 page areas (recommended), B No Area field
Answer: A. Areas: Explore, Efforts, Sightings, Individuals, Export, SQL, Track File Manager, Audit Log, Settings, Sign In And Accounts, Other. The rest of the form stays as V1 (Title, Details, Type, up to 3 pictures, opens a GitHub issue).
Affects: spec.md Feedback, mockups/feedback.html

### Q-052: Extra Features (Phase 1)
Asked: 2026-11-26
Options (multi-select): Global ID Search, Individual Filter, Density Layer, Dark Mode
Answer: Global ID Search, extended to "global search with fuzzy resolving", and the Individual Filter. Density Layer and Dark Mode are not in V2. The scope of fuzzy resolving is asked as Q-053.
Affects: spec.md Search, Explore and Sightings filters

### Q-053: Global Search Scope (Phase 1)
Asked: 2026-11-26
Options: A IDs and names with typo tolerance (recommended), B IDs only, C Plus comments
Answer: A. Searches record IDs (effort, sighting and sample numbers, whale IDs, aliases, retired IDs, cross-catalog IDs) and names (vessels, localities, species common and scientific). Ignores case, spaces, dashes and prefixes; tolerates small typos in names with Postgres `pg_trgm`. Results grouped by kind, best first, up to 5 per kind; Enter opens the best match; a vessel, locality or species opens Sightings filtered by it.
Affects: spec.md Search, sidebar in every mockup

### Q-054: Gap Rule Defaults (Phase 1)
Asked: 2026-11-26
Options: A As stated (recommended), B Speed on at 40 kn
Answer: A. Confirms the Q-029 assumption: defaults 30 minutes, distance off, speed off; ranges 1 to 240 minutes, 50 to 50,000 m, 5 to 100 kn. Assumption closed.
Affects: spec.md Track Display Settings

### Q-055: HappyWhale Link (Phase 1)
Asked: 2026-11-26
Options: A Show link (recommended), B Don't show
Answer: A. Confirms the Q-036 assumption: the Individual page's Sightings table has a HappyWhale link column that opens in a new tab. Assumption closed.
Affects: spec.md Individual, mockups/individual.html

### Q-056: Feedback Pictures (Phase 1)
Asked: 2026-11-26
Context: Brandon dropped assumption A-10 ("you're overreading into the rule"): Q-002's "nothing public" was never meant to cover feedback pictures, so the note in Q-016 that pictures move behind the login was the agent's over-reading and is withdrawn. He asked why the site stores pictures at all. Finding: GitHub's REST API has no documented endpoint to attach an image to an issue, which is why V1 stores and serves them. The GitHub CLI can (`gh issue create --attach`, per GitHub's docs), though the API underneath is not documented and the local gh 2.92.0 does not list the flag yet.
Options: A gh CLI attach (recommended), B Commit pictures to a branch, C No pictures in the form
Answer: A. The server holds uploaded pictures only for the request and creates the issue with `gh issue create --attach`, so pictures live inline on GitHub and the site stores none. Needs a recent gh on the server and a token with push access.
Affects: spec.md FDBK-02, FDBK-03; Phase 4 server setup (gh)

### Q-057: Spec Assumptions A-01 To A-10 (Phase 1)
Asked: 2026-11-26
Answer: A-01 to A-07 and A-09 confirmed as written. A-10 dropped (Q-056). A-08 rejected: drawing a line through an effort's recorded positions when it has no track file is a user track setting, not fixed behaviour.
Affects: spec.md section 7, EDET-05, SET-02, TRACK-03

### Q-058: No-Track Path Default (Phase 1)
Asked: 2026-11-26
Options: A On by default, as V1 (recommended), B Off by default
Answer: A. The No-Track Path setting is on by default. Closes assumption A-11; the spec has no open assumptions.
Affects: spec.md TRACK-08

### Q-059: Phase 5 As One Step (Workflow)
Asked: 2026-11-26 (raised by Brandon while reviewing the full plan)
Answer: The Phase 5 build is one step, not one branch and pull request per feature as `phase-5-build.md` describes. Everything else in the five-phase plan stands. `phase-5-build.md` is Brandon-only, so he updates it; the agent follows this answer in the meantime.
Affects: docs/workflow/phase-5-build.md (Brandon), Phase 5 working method

### Q-060: Site Name (Phase 1)
Asked: 2026-11-26, after the mockup review
Options: Keep "Cascadia DB" (used in the mockups), or another name
Answer: The site is named Unified DB. Brandon typed "Unified Db"; the agent writes "Unified DB" with DB in capitals, as in "Cascadia DB", and flagged it for him to correct if he wants "Db". Brandon also said the mockups look fine for now.
Affects: spec.md NAV-01, AUTH-01, Purpose; every mockup (sidebar, page titles, Sign In)

### Q-061: Reference Screenshots (Phase 1)
Asked: 2026-11-26 (Brandon stopped the screenshot capture)
Answer: Skip the reference screenshots in `docs/ui/` (Phase 1, step 5). The build will probably not match exactly what Brandon wants, and that is fine: the site is refined through his feedback after it is built, so some drift from the mockups is acceptable. The mockups in `mockups/` stay as the visual reference. `phase-1-spec-and-mockup.md` and `phase-5-build.md` still mention `docs/ui/`; they are Brandon-only, so he updates them if he wants the docs to match.
Affects: Phase 1 exit checklist (screenshots), Phase 5 "match the approved screenshot" steps

## Phase 2: Schema And DuckLake

### Q-062: Catalog Model (Phase 2, Round 1)
Asked: 2026-11-27
Options: A generic tables (catalog, individual, individual_id, catalog_record, catalog_sample) with catalog-only fields in one jsonb `extra` column (recommended), B the same tables with every MnID column as a real column, C a set of tables per catalog
Answer: Five tables is overkill. The jsonb `extra` column is the right pattern, but the design does far too much. A leaner model goes back to Brandon in round 2.
Affects: decision 001 (catalogs), schema.md photo-ID tables

### Q-063: Primary Keys (Phase 2, Round 1)
Asked: 2026-11-27
Options: A hashed keys as in V1, with the DB167 ID kept as `legacy_id` for display and URLs (recommended), B Postgres identity keys mapped back through a lookup table, C DB167 IDs as primary keys
Answer: A. Hashed keys, as V1.
Affects: decision 002 (keys), every survey table

### Q-064: Audit Approach (Phase 2, Round 1)
Asked: 2026-11-27
Options: A one `audit_entry` table written by the app and the pipeline (recommended), B django-pghistory, C django-simple-history, D valid-from/valid-to history tables
Answer: D, with changes. Use valid_from and valid_to, with columns for who and why. Undo does not delete rows: reverting writes a new row that copies the version being reverted to and makes it the valid one. Data rarely changes, so table growth is no concern. Brandon also noted the options did not explain how dbt would write into the design; the next round must.
Affects: decision 004 (audit), audit.md; conflicts with the frozen spec (AUD-04 and related), raised as CR-001

### Q-065: Rebuild Against Website Edit (Phase 2, Round 1)
Asked: 2026-11-27
Options: A replay an edit until the source changes that field, as V1 (recommended), B the edit always wins, C the source always wins
Answer: None of these. Assume an incremental loading strategy in which the original database is not edited directly. There are no full rebuilds to replay edits over.
Affects: decision 004 (audit), the pipeline contract in audit.md

### Q-066: Lean Catalog Model (Phase 2, Round 2)
Asked: 2026-11-27
Options: A two tables plus one column on samples: `individual` (catalog code, number, species, sex, colour category, dead; other IDs and `extra` in jsonb) and `identification` (survey identifications and MnID photo-ID records together); MnID samples join `sample` with `individual_id` and `extra` (recommended), B three tables, with MnID photo-ID records in their own `catalog_record`
Answer: A.
Affects: decision 001 (catalogs), schema.md photo-ID tables

### Q-067: Where Versions Live (Phase 2, Round 2)
Asked: 2026-11-27
Options: A every version in one table per record type, with a `_current` view; links checked by dbt tests rather than foreign keys (recommended), B a current table plus a `_history` table per record type
Answer: A.
Affects: decision 004 (audit), schema.md, audit.md

### Q-068: Pipeline Version Against a Person's Edit (Phase 2, Round 2)
Asked: 2026-11-27
Options: A the newest version wins; the pipeline adds a version only when the source row changed, B a person's edit is never overwritten and the pipeline's change is held for review
Answer: Neither is needed. Loading is incremental and only loads data not loaded before, so the pipeline adds new records and never sends a new version of a record already loaded. The question does not arise, and the design needs no source hash.
Affects: decision 004 (audit), the pipeline contract in audit.md

### Q-069: Restoring Versions From Before a Pipeline Change (Phase 2, Round 2)
Asked: 2026-11-27
Options: A any version can be restored, one rule for all (recommended), B keep AUD-05: only versions written by people can be restored
Answer: A. Any version can be restored. AUD-05 changes; added to CR-001.
Affects: spec.md AUD-05 (through CR-001), audit.md

### Q-070: DuckLake Catalog Location (Phase 2, Round 3)
Asked: 2026-11-27
Options: A a `ducklake` schema in the same Postgres database (recommended), B a DuckDB file, C a SQLite file
Answer: A. Applies only if DuckLake stays in the design (see Q-072).
Affects: decision 003 (tracks), ducklake.md

### Q-071: What the PostGIS Copy of Tracks Holds (Phase 2, Round 3)
Asked: 2026-11-27
Options: A every point plus 11 m and 550 m lines whose vertices carry times and step maxima, so gap rules run in the browser (recommended), B every point only, C lines only
Answer: A.
Affects: decision 003 (tracks), schema.md track tables

### Q-072: Keeping PostGIS in Step With DuckLake (Phase 2, Round 3)
Asked: 2026-11-27
Options: A write path plus nightly check (recommended), B nightly rebuild, C pg_duckdb with no copy
Answer: Brandon asked about pg_duckdb. The point of DuckLake was to get GPS tracks out of CSV files so PostGIS can query them; if Postgres can run those queries on DuckLake tables, a full PostGIS copy is redundant. Researched and answered in round 4.

### Q-073: Parquet for the SQL Page (Phase 2, Round 3)
Asked: 2026-11-27
Answer: Brandon asked what the question meant. Re-asked in round 4 with an explanation.

### Q-074: Parquet for the SQL Page, Re-Asked (Phase 2, Round 4)
Asked: 2026-11-27
Options: A current rows of every table, 11 m track lines and all GPS points split by year, fetched by range requests and rewritten after loads and edits (recommended), B the same plus every version, C current rows and lines only
Answer: A.
Affects: decision 005 (analysis access), SQL-01

### Q-075: Where GPS Points Live (Phase 2, Round 4)
Asked: 2026-11-27
Options: A PostGIS only, dropping DuckLake (recommended), B DuckLake as source of truth plus the PostGIS copy
Answer: Brandon asked how hard it would be to extend pg_ducklake to support PostGIS queries, and what the pg_duckdb spatial discussion's status means. Researched and answered in round 5.

### Q-076: Where GPS Points Live, After Research (Phase 2, Round 5)
Asked: 2026-11-27
Findings shown: pg_duckdb runs a query that touches a DuckLake table in DuckDB's engine, which cannot call Postgres functions (pg_duckdb issue #615, open since February 2025, milestone "Long term"); PostGIS support in pg_duckdb is an open discussion (#606) with nothing built; DuckLake tables have no GiST index; Snowflake's pg_lake does PostGIS over Iceberg (not DuckLake) by translating functions one by one. Extending pg_ducklake would be a C++ fork of pg_duckdb's planner.
Options: A PostGIS only, dropping DuckLake (recommended), B DuckLake as source of truth plus a PostGIS copy, C pg_lake with Iceberg tables
Answer: B. DuckLake stays the source of truth (V2Spec, Q-028). Each track write goes to DuckLake first and then rebuilds that track in PostGIS, stamped with the DuckLake snapshot; a nightly check rebuilds any track whose stamp differs. This also settles Q-072 (sync) and Q-075.
Affects: decision 003 (tracks), ducklake.md, schema.md track tables

### Q-077: Roles in Django (Phase 2, Round 6)
Asked: 2026-11-27
Options: A six custom permissions (browse, edit_records, manage_tracks, manage_audit, manage_users, view_server) on a tableless model, assigned to the five Groups by a migration from code; views use permission_required; Django Admin checks manage_users instead of is_staff (recommended), B check group names in views, C Django's per-table permissions
Answer: A.
Affects: decision 006 (roles), ROLE-01 to ROLE-06

### Q-078: Track Storage in PostGIS, Rejected as Bloated (Phase 2, Review)
Asked: 2026-11-27 (Brandon, reviewing the schema)
Answer: Four tables for tracks is bloat, and 10 million point rows is wrong. Store one track per row as a MultiLineStringM. Replaces Q-071. The agent's design: `gold.track.geom` holds every fix with M = the fix time; a new part starts where fixes are more than 60 s apart (the smallest gap setting), so time gaps fall between parts and each user's rules still apply in the browser; generated columns hold Explore's 550 m line, point count, length and top speed; the three copy tables are gone.
Affects: schema.sql, schema.md, ducklake.md, audit.md, decision 003


### Q-079: Redundant Version Columns (Phase 2, Bloat Pass)
Asked: 2026-11-27 (after Brandon asked what a "fix" is, the Phase 2 docs say "GPS point" instead; `fix_time` became `point_time`)
Options: drop `change_source` (same as `changed_by` being empty) and `deleted` (same as `change_type = 'delete'`) from all 11 versioned tables (recommended), drop `change_source` only, keep both
Answer: Drop both.
Affects: schema.sql, schema.md, audit.md, decision 004

### Q-080: Track Status and Track-Only Change Types (Phase 2, Bloat Pass)
Asked: 2026-11-27
Options: drop `status` (matched = has an effort, blank = no points; all 1,570 V1 tracks fit) and fold import, replace_points, match, unmatch, create_from_positions into edit (recommended), drop status only, keep both
Answer: Drop both. `track_current` computes the status.
Affects: schema.sql, schema.md, audit.md, ducklake.md

### Q-081: Summary Views (Phase 2, Bloat Pass)
Asked: 2026-11-27
Options: as plain queries on full-size invented rows, place_name took 7 ms, effort_summary 70 ms and individual_summary 320 ms (`scratch/pgcheck/summary_timing.sql`). Make place_name and effort_summary plain views and keep individual_summary materialized (recommended), place_name only, keep all three
Answer: place_name and effort_summary become plain views. Phase 4 re-times effort_summary on the droplet.
Affects: schema.sql, schema.md

### Q-082: DuckLake Role for Tracks (Phase 2, Bloat Pass)
Asked: 2026-11-27
Options: since Q-078 Postgres holds every point of every track version, so DuckLake duplicates it. A Postgres is the source and DuckLake is a copy rewritten per track after each save, dropping `ducklake_snapshot_id`, the commit-message rule and the repair job (recommended); B drop DuckLake for tracks and write Parquet and raw files from `geom`; C keep DuckLake as the source
Answer: A.
Affects: schema.sql, ducklake.md, decision 003, audit.md, synthetic-data-profile.md

### Q-083: Review Items Settled While Writing the Schema (Phase 2, Review)
Asked: 2026-11-27 (assumptions listed for confirmation before the phase closes)
Items: (1) an individual's key is a hash of (catalog, number), and its URL is `/individuals/mn-20417/` (decision 002); (2) survey dates and times are stored as recorded, with no time zone, while GPS point times and version times are UTC; (3) no check constraints on measured values, and the pipeline's tests flag oddities; (4) real species names, event codes and harbour names in the synthetic data, as public reference lists, with every record, person and track invented
Answer: "Yes, all four hold."
Affects: decision 002, schema.sql, synthetic-data-profile.md

## Phase 3: Quality Gates

### Q-084: Type Checking (Phase 3, Round 1)
Asked: 2026-11-27
Options: mypy with django-stubs, moderate (check_untyped_defs, warn_unused_ignores, annotations not forced), at commit and in CI (recommended); mypy strict; none
Answer: mypy moderate.
Affects: quality-gates.md

### Q-085: Test Bar (Phase 3, Round 1)
Asked: 2026-11-27
Options: every one of the 159 spec IDs cited by a test (or mapped to a gate) plus 85% line and branch coverage (recommended); IDs only; IDs plus 95%
Answer: IDs plus 85% coverage.
Affects: quality-gates.md, definition-of-done.md

### Q-086: Browser Tests (Phase 3, Round 1)
Asked: 2026-11-27
Options: Playwright smoke test per page in CI (loads, no console errors, main element present) (recommended); none; full user flows
Answer: Playwright smoke.
Affects: quality-gates.md

### Q-087: Before-Done Claude Hook (Phase 3, Round 2)
Asked: 2026-11-27 (after Brandon clarified that by "hooks" he means Claude Code hooks)
Options: a Stop hook that blocks the agent from ending a turn until the full suite (types, Django checks, all tests, browser page checks; about 1-3 min) passes (recommended); run and only warn; per-file checks only
Answer: Block until green.
Affects: quality-gates.md

### Q-088: GitHub Checks as a Safety Net (Phase 3, Round 2)
Asked: 2026-11-27
Options: GitHub also runs the full suite on every push, for changes made outside the Claude hooks (recommended); Claude hooks only
Answer: Keep GitHub too.
Affects: quality-gates.md

### Q-089: Extra Checks (Phase 3, Rounds 1 and 2)
Asked: 2026-11-27
Options offered: pip-audit, a speed budget, import-linter, vulture
Answer: Brandon asked instead for proposals of additional Claude hooks that raise code quality. Asked again as Q-090 and Q-091.
Affects: quality-gates.md

### Q-090: Brandon's Own Hook Rules (Phase 3, Round 3)
Asked: 2026-11-27 (in answer to the proposed "stop gaming the checks" hooks)
Answer, in Brandon's words: "exactly one comment is allowed at the beginner of a file. helper functions blocked if they are not used at least 3 times. other way around applies too, the same code reapplied 3 times is blocked". Scope questions asked as Q-093 to Q-096.
Affects: quality-gates.md, style-guide.md

### Q-091: AI-Habit Hooks (Phase 3, Round 3)
Asked: 2026-11-27
Options: copy-paste detector, second-Claude review, session-start reminder, package security check
Answer: "Something else", with no detail. Asked again in Q-096.
Affects: quality-gates.md

### Q-092: Weekly Speed Check (Phase 3, Round 3)
Asked: 2026-11-27
Options: weekly GitHub run timing the slowest pages on full-size data (recommended); no
Answer: No weekly speed check. Per-page query limits in the tests stay.
Affects: quality-gates.md

### Q-093: One-Comment Rule and Docstrings (Phase 3, Round 4)
Asked: 2026-11-27
Options: docstrings banned too; docstrings allowed
Answer: Docstrings allowed. One comment at the top of each file, nothing else; check-disabling comments (`# noqa`, `# type: ignore` and the like) are therefore banned outright. Applies to Python, templates, JavaScript and CSS.
Affects: quality-gates.md, style-guide.md

### Q-094: What Counts as a Helper (Phase 3, Round 4)
Asked: 2026-11-27
Options: exempt Django entry points (views, model and form methods, template tags, management commands, tests), with calls from tests not counting toward 3 (recommended); every function
Answer: Exempt Django entry points.
Affects: quality-gates.md

### Q-095: Repeated Block Size (Phase 3, Round 4)
Asked: 2026-11-27
Options: 5 lines or more (recommended); 3 or more; 10 or more
Answer: 5 lines or more. A block of 5+ lines appearing 3 times is blocked.
Affects: quality-gates.md

### Q-096: Other Proposed Hooks (Phase 3, Round 4)
Asked: 2026-11-27
Options: check settings locked to Brandon; code changes need test changes; new packages, apps and JS files need Brandon's OK; second-Claude review
Answer: Only the review, as "seocnd claude review, quick Haiku Agent. its asked to follow the style guide, look for logic thats overly complicated, slop, etc". The other three are not chosen.
Affects: quality-gates.md

### Q-097: App Layout (Phase 3, Round 5)
Asked: 2026-11-27
Options: one app per sidebar group (survey, photoid, data, manage, plus core) (recommended); one app per page; one app
Answer: Per sidebar group.
Affects: style-guide.md

### Q-098: How Pages Are Written (Phase 3, Round 5)
Asked: 2026-11-27
Options: plain functions (recommended); class-based views; a mix
Answer: Brandon asked for an example first. Asked again with one.
Affects: style-guide.md

### Q-099: Hand-Written JavaScript (Phase 3, Round 5)
Asked: 2026-11-27
Options: maps only with a 1,500-line cap (recommended); maps only, no cap; no extra rule
Answer: "only when the implementation is genuinely more clean and straightforward then htmx. do not force htmxx for the sake of htmx if a bit of javascript is simplier". No line cap; the choice is judged case by case (the Haiku review checks it).
Affects: style-guide.md

### Q-100: Package Security Check and Session-Start Reminder (Phase 3, Round 5)
Asked: 2026-11-27
Options: package security check (pip-audit) when the package list changes; style rules printed at session start
Answer: Neither.
Affects: quality-gates.md

### Q-101: How Pages Are Written, With an Example (Phase 3, Round 6)
Asked: 2026-11-27 (the Sighting page shown as a plain function and as a class-based view; the question box hid the first example, so it was repeated in plain text)
Options: A plain functions everywhere (recommended); B class-based views; C a mix
Answer: A.
Affects: style-guide.md

### Q-102: Phase 3 Assumptions (Phase 3, Review)
Asked: 2026-11-27 (ten assumptions listed in STATUS.md and in chat before approval)
Answer: Brandon approved Phase 3 after they were listed, so all ten stand as written in STATUS.md and the quality documents.
Affects: quality-gates.md, style-guide.md

## Phase 4: Scaffolding

### Q-103: Local Database (Phase 4, Round 1)
Asked: 2026-11-27
Options: a separate project Postgres run from the installed PostgreSQL 18, with its data in `local/`, its own port, local connections only and no password, started by a script (recommended); a new database in Brandon's existing service, with its password in `.env`
Answer: Separate project Postgres.
Affects: local/ setup scripts, settings, gate runner

### Q-104: Map Shapes in Django (Phase 4, Round 1)
Asked: 2026-11-27
Options: keep shapes in the database and send GeoJSON, with no GDAL on Windows (recommended); GeoDjango as in V1, needing GDAL and GEOS on Windows
Answer: GeoDjango. On Windows it uses the GDAL and GEOS DLLs that the PostGIS bundle installs in PostgreSQL's `bin` folder.
Affects: settings, models, local/ setup, Dockerfile
