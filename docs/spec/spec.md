# Cascadia DB V2 Spec

Status: draft for Brandon's review (Phase 1, step 3).

Sources: [V2Spec.MD](../../V2Spec.MD), [v1-inventory.md](v1-inventory.md) (V1 at `3a637f1`, confirmed in Q-017), and every answer in [questions-log.md](../workflow/questions-log.md). Each section cites the questions it rests on as `(Q-nnn)`.

How to read the requirements: each has a stable ID that Phase 5 tests cite, and a **Check** column that says what a test asserts. "V1" means the behaviour of V1 at `3a637f1`, described in the inventory.

## 1. Purpose, Goals and Non-Goals

### Purpose

Cascadia DB V2 builds **Unified DB**, the internal website of Cascadia Research Collective (Q-060). People use it to explore marine mammal survey records (efforts, sightings, GPS tracks, samples) and the photo-ID catalogs, to fix GPS track files, to review changes and restore earlier versions, and to take data away for analysis. It is a partial rebuild of V1 to a new spec, with clean, simple code.

### Goals

1. One clean Django codebase. Each app has its own `urls.py`, files stay under 500 lines, and custom JavaScript is kept small. Established libraries (MapLibre, deck.gl, DuckDB WASM) are fine (Q-006).
2. A Databricks-style sidebar instead of V1's top bar (Q-019).
3. Faster maps on WebGL (MapLibre GL JS plus deck.gl) instead of Leaflet (Q-003).
4. One implementation of GPS tracks, with display settings each user controls (Q-025 to Q-030).
5. A simple permission model of five roles (Q-013, Q-021).
6. Exploration-first analysis: export whole gold tables and filtered lists, and query gold data with read-only SQL in the browser (Q-004, Q-006, Q-041, Q-042).
7. One audit log for changes by people and by the pipeline, whose History view explains each record's current state (Q-018, Q-044).
8. Photo-ID catalogs (MnID now, Bm and ErId later) on the same site, with no schema change for a new catalog (Q-033).

### Non-Goals

- No public pages (Q-002).
- No writing back to DB167 (Q-015).
- No editing of photo-ID catalog data on the site (Q-049).
- No dbt models in this rebuild; the design leaves room for them (V2Spec).
- See section 6 for the full list.

## 2. Users and Permissions

Access comes only from roles. A role is a Django Group. One person may hold several roles; their access is the union. There are no one-off permission grants per user (Q-013).

| ID | Requirement | Check |
|---|---|---|
| ROLE-01 | Exactly five roles exist: Viewer, Editor, Track Manager, Audit Manager, Admin (Q-013). | After setup, the Groups table holds exactly these five names. |
| ROLE-02 | Each role grants the actions in the table below and nothing else (Q-021). | For every role and every row, a test signs in as a user holding only that role and gets 200 for "Yes" and 403 for blank. |
| ROLE-03 | A user's access is the union of their roles. | A user holding Track Manager and Audit Manager can open both the Track File Manager and the Audit Log. |
| ROLE-04 | A signed-in user with no role can do nothing but sign out; every other page returns 403 with the ERR-04 message naming the Viewer role. | A no-role user gets 403 on `/explore/`. |
| ROLE-05 | Role setup never overwrites role memberships set by an Admin, and the role definitions live in code, not in admin-edited group permissions. | Running setup twice leaves user memberships unchanged. |
| ROLE-06 | Controls a user cannot use are not shown (buttons, sidebar links). | A Viewer's effort page has no Edit, Delete or track buttons. |

| Action | Viewer | Editor | Track Manager | Audit Manager | Admin |
|---|---|---|---|---|---|
| Browse Explore, Efforts, Sightings, Individuals, record History | Yes | Yes | Yes | Yes | Yes |
| Export and SQL (Q-014) | Yes | Yes | Yes | Yes | Yes |
| Feedback, Settings, change own password | Yes | Yes | Yes | Yes | Yes |
| Edit and delete efforts and sightings | | Yes | Yes | Yes | Yes |
| Track File Manager, and track buttons on effort pages | | | Yes | | Yes |
| Audit Log page, and Restore any version | | | | Yes | Yes |
| Users and roles | | | | | Admin only |
| Server page | | | | | Admin only |

Photo-ID catalog data cannot be edited by any role (Q-049).

## 3. Information Architecture

### Sidebar (Q-019, Q-033, Q-053)

| ID | Requirement | Check |
|---|---|---|
| NAV-01 | Every signed-in page has a left sidebar with, in order: the logo and the site name "Unified DB" (Q-060); the Global Search box (SRCH); group **Survey** (Explore, Efforts, Sightings); group **Photo-ID** (Individuals); group **Data** (Export, SQL); group **Manage** (Track File Manager, Audit Log, Users, Server); and at the bottom Feedback, Settings, and the user's name with Sign Out. | The rendered sidebar for an Admin lists these links in this order. |
| NAV-02 | A link shows only to roles that can open it (ROLE-06). The Manage group is hidden when it would be empty. | A Viewer's sidebar has no Manage group; a Track Manager's Manage group holds only Track File Manager. |
| NAV-03 | The current page's link is marked active. | On `/sightings/`, the Sightings link has the active state. |
| NAV-04 | The Export link shows how many queries are on the export stack, for example "Export (3)", when there are any. | After adding two queries, the link reads "Export (2)". |
| NAV-05 | `/` redirects to Explore, and signing in lands on Explore unless a `next` page was requested (Q-020). | GET `/` returns a redirect to `/explore/`. |
| NAV-06 | Below 768 px wide, the sidebar collapses behind a menu button (Q-057). | At 390 px wide the sidebar is hidden until the menu button is pressed. |

### URL Map

Each Django app owns its URLs in its own `urls.py`, included from the project `urls.py` (V2Spec). App names are proposals for Phase 4; the URLs are the spec.

| URL | Page | App |
|---|---|---|
| `/login/`, `/logout/` | Sign in, sign out | `accounts` |
| `/settings/` | Settings (includes change password) | `accounts` |
| `/` | Redirect to Explore | `survey` |
| `/explore/` | Explore | `survey` |
| `/efforts/`, `/efforts/<id>/`, `/efforts/<id>/edit/`, `/efforts/<id>/delete/` | Efforts list, detail, edit, delete | `survey` |
| `/sightings/`, `/sightings/<id>/`, `/sightings/<id>/edit/`, `/sightings/<id>/delete/` | Sightings list, detail, edit, delete | `survey` |
| `/api/...` | Map data for Explore and detail maps | `survey` |
| `/individuals/`, `/individuals/<id>/` | Individuals list, Individual | `photoid` |
| `/export/` and its actions | Export | `exports` |
| `/sql/` | SQL | `exports` |
| `/tracks/` and its actions | Track File Manager | `tracks` |
| `/audit/`, `/audit/<id>/` | Audit Log, Audit Entry | `audit` |
| `/server/` | Server | `server` |
| `/feedback/` | Feedback | `feedback` |
| `/search/` | Global Search results | `search` |
| `/admin/` | Django Admin, users and roles only | Django |

`<id>` is the record's public number (the legacy effort or sighting number, or the catalog ID for an individual).

## 4. Pages

Every page needs a login (Q-002), uses the sidebar (NAV-01) and follows the empty and error states in ERR.

### 4.1 Sign In and Sign Out

| ID | Requirement | Check |
|---|---|---|
| AUTH-01 | `/login/` shows the logo, "Unified DB", Username and Password, and has no sidebar. A wrong pair shows "That username and password do not match an account." | POST with a bad password returns the page with that message. |
| AUTH-02 | Every other URL redirects a signed-out visitor to `/login/?next=<url>` (Q-002). | GET `/efforts/` signed out redirects to login. |
| AUTH-03 | Sign Out is a POST from the sidebar and returns to `/login/`. | GET `/logout/` does not sign out; POST does. |

### 4.2 Explore (`/explore/`)

Purpose: see survey sightings and tracks on a map and narrow them with filters. It is the landing page (Q-020).

| ID | Requirement | Check |
|---|---|---|
| EXPL-01 | Three columns: the filter panel (FILT), the map (MAP), and the results panel. The side panels can be resized. | The page has all three regions. |
| EXPL-02 | The map shows every matching sighting with a position as a dot in its species colour, sized `min(3 + sqrt(group size) * 1.2, 12)` px, or 3 px when size is unknown, plus the matching efforts' tracks through the track component (TRACK). | With a filter matching 3 positioned sightings, the map source holds 3 points. |
| EXPL-03 | The map legend has toggles for Tracks, Sightings and Group Into Clusters, and a species legend: one row per animal group (Generic profile) or the 9 species most seen in the current results (Cascadia profile). Turning Tracks off hides gap joins too. | Unticking Tracks leaves no track or gap layer drawn. |
| EXPL-04 | Map tools: Fullscreen, Screenshot (a PNG with a caption of counts and applied filters), the Clustering toggle, and drawing an area (polygon or rectangle) for the area filter. There is no Measure tool (Q-031). | Each control is present; there is no measure control. |
| EXPL-05 | A sighting popup shows species, year, "About N animals" and Open Sighting. A track popup shows Effort Date, Vessel, Research Group, File, Points, Length, a Suspect pill when suspect, Open Effort, and Open in Track File Manager for Track Manager and Admin. | Popup content matches a known record. |
| EXPL-06 | The results panel has tabs Sightings (the default) and Efforts. It shows "N sightings across M efforts", "N without a position are not on the map" when any exist, the first 300 rows of the open tab, "Showing the first 300 of N" beyond that, Open As a List (same filters) and Add to Export (Q-037). | With 301 matches, 300 rows and the note show. |
| EXPL-07 | The applied filters are written out above the results, for example "Showing CRC sightings of Humpback Whale in 2024". V1 computed this but never showed it. | The sentence names each applied filter. |
| EXPL-08 | Clicking a result row or a popup link opens the record in the modal (MODAL). | The click opens the modal and pushes the record URL. |
| EXPL-09 | The map view, basemap, overlay, layer toggles and open filter sections are kept in the URL, so a link reopens the same view. | Reloading the URL restores the view. |

### 4.3 Efforts List (`/efforts/`)

| ID | Requirement | Check |
|---|---|---|
| EFF-01 | Columns: Date, Effort, Vessel, Locality, Survey Type, Track, Distance (nm), Sightings (Q-038). Track is a pill: No Track File, Available or Blank. | The header row matches. |
| EFF-02 | Every column sorts. Clicking the sorted column again reverses it, and sorting returns to page 1. The default is newest date first. Vessel sorts by name (Q-038). | `?sort=vessel` orders by vessel name. |
| EFF-03 | 50 rows per page with no page-size picker. Pagination shows first, previous, next, last, nearby page numbers and "A–B of N" (Q-024). | 120 matches give 3 pages. |
| EFF-04 | The filter panel (FILT), without the filters that apply only to sightings. | There is no Species filter on this page. |
| EFF-05 | Clicking a row opens the effort in the modal. Add to Export adds the current filters to the export stack. | The stack count goes up by one. |

### 4.4 Effort Detail (`/efforts/<id>/`)

| ID | Requirement | Check |
|---|---|---|
| EDET-01 | Header "Effort N" with record tools: Add to Export, Edit and Delete (Editor and above), History. | A Viewer sees Add to Export and History only. |
| EDET-02 | Summary: Date, Time, Vessel, Locality, Region, Sub-Area, Survey Type, Time Searching, Sightings, and Comments when present. Sub-Area appears once on the page (V1 showed it twice). | Sub-Area appears exactly once. |
| EDET-03 | GPS Data: Start and End positions, each with its source (for example "Log Entry (Begin)", "GPS Track (Start)", "Earliest Position (Not Departure)"), and the track file's status. | The source label matches the stored source. |
| EDET-04 | Map: the effort's one GPS track through the track component at the stored resolution, about 11 m (Q-008, Q-028), with green start and red end markers and the effort's sightings. A suspect track is drawn red and dashed, left out of the map framing, and a notice explains it. | A suspect track shows the notice. |
| EDET-05 | With no track file and the No-Track Path setting on (TRACK-08), a dashed line joins the effort's recorded timeline positions in time order, with a popup saying it is not a GPS track (Q-057). | With the setting on, an effort with no track shows the joined line; with it off, none. |
| EDET-06 | Sightings card: one row per species, "N sightings, M animals", or "No sightings were recorded on this effort." | The empty text shows for an effort with no sightings. |
| EDET-07 | Extra Info (collapsed): Crew, Objective, Launch, Return, Off Effort, Research Group, and the distance check (recorded nm, GPS track length, difference and percent, with notes for a suspect or untimed track). | |
| EDET-08 | Track card: File, Status, Source, Points, Length (nm), and a Suspect pill. Track Manager and Admin also get Open in Track File Manager, Change Track File and Delete. With no track they get Add Track File, Create Track From Positions (when at least 2 positioned timeline rows exist) and Choose Existing File. | A Viewer sees no track buttons. |
| EDET-09 | Timeline (collapsed): Time, Kind (Weather Reading, Log Entry, Sighting), Detail, Position. Sighting rows open the sighting. Empty: "Nothing was recorded during this effort." | |

### 4.5 Sightings List (`/sightings/`)

| ID | Requirement | Check |
|---|---|---|
| SIGHT-01 | Columns: Date, Time, Sighting, Species, Group Size, Min–Max, Vessel, Position, Effort (Q-038). Species may carry the pills Two Species, Uncertain and Name Unconfirmed; Min–Max may carry Disagrees. | The header row matches. |
| SIGHT-02 | Sorting and paging as EFF-02 and EFF-03. | |
| SIGHT-03 | The full filter panel (FILT), including Individual (Q-052). | Filtering by a whale ID returns only sightings where it was identified. |
| SIGHT-04 | Rows open the modal. Add to Export adds the current filters. | |

### 4.6 Sighting Detail (`/sightings/<id>/`)

| ID | Requirement | Check |
|---|---|---|
| SDET-01 | Header "Sighting N" with record tools as EDET-01. | |
| SDET-02 | Summary: Species (scientific and common name, with pills), Date, Time, Vessel, Group Size, Comments. GPS Data: position with position type, and end position. | |
| SDET-03 | Map: the sighting and its effort's track through the track component, with the same settings as everywhere, including gaps and the suspect style, which V1 left out here. | A suspect effort track is red and dashed on the sighting map. |
| SDET-04 | Effort card: Effort (link), Date, Vessel, Locality, Region, Sub-Area, Survey Type; or "This sighting is not attached to any effort." | |
| SDET-05 | Extra Info (collapsed): Group Behaviour, Group Type, Sighting Type, Photos Taken, Individuals Identified, Calves, Minimum, Maximum, Depth, Number on the Day, Research Group. | |
| SDET-06 | Samples: Number, Type, Species, Preservation, Taken By; or "No samples were taken at this sighting." | |
| SDET-07 | Attached records, shown only when present: Sighting Events, Other Species Present, Tag Deployments, Individuals Identified. Each individual links to its Individual page. | An individual row links to `/individuals/<id>/`. |

### 4.7 Edit and Delete (Efforts and Sightings)

| ID | Requirement | Check |
|---|---|---|
| EDIT-01 | Editor and above only (ROLE-02). | A Viewer gets 403. |
| EDIT-02 | Editable sighting fields (18): Species, Sighting Number, Date, Time, Latitude, Longitude, End Latitude, End Longitude, Position Type (Precise, Calculated, Estimated, General), Sighting Type (S, SBE, SE, UNK), Best, Smallest and Largest Estimate, Calves, Group Behaviour, Group Type, Depth (m), Comments. | The form has exactly these fields. |
| EDIT-03 | Editable effort fields (13): Date, Start Time, End Time, Launch, Locality, Return, Region, Sub-Area, Survey Type, Project or Objective, Personnel, Distance (nm), Comments. | The form has exactly these fields. |
| EDIT-04 | Two steps: the form (Review Changes is disabled until a value changes), then a Field, From, To table with an optional Why note and Save These Changes. Only changed fields are written, through the audit log. | Saving one change writes one audit entry with one field. |
| EDIT-05 | Every input is validated. A bad number, date or time is shown against its field and nothing is saved (ERR-05). V1 showed an error page instead. | Latitude "abc" shows a field error. |
| EDIT-06 | Delete lists the dependent records that go with it, counted per type ("3 sightings, 12 log entries"), takes an optional note, and says the record can be put back from the Audit Log. The delete writes a deleted version of the record and of every dependent, under one change, so restoring the version before it brings them all back (CR-001). | Delete, then Restore This Version on the version before it, brings back the record and its dependents. |
| EDIT-07 | After a save or delete, a message confirms it and the page under the modal reloads. | |

### 4.8 Individuals (`/individuals/`)

One list across all photo-ID catalogs (Q-033, Q-039). Read only (Q-049).

| ID | Requirement | Check |
|---|---|---|
| IND-01 | Columns: ID, Species, Other IDs (shortened), Colour Category, Sex (genetic where known, otherwise behavioural), First Seen, Last Seen, Sightings, Dead. | The header row matches. |
| IND-02 | Filters: Species, one search box matching any ID, alias, retired ID or cross-catalog ID, Years Seen, Region Seen, Dead. | Searching a retired ID finds the current individual. |
| IND-03 | The default sort is Last Seen, newest first. Every column sorts. 50 per page with no picker. | |
| IND-04 | A new catalog (for example Bm or ErId) appears in the list and the Species filter once imported, with no code or schema change. | Adding a catalog's rows to test data shows them. |
| IND-05 | Rows open the Individual in the modal. | |

### 4.9 Individual (`/individuals/<id>/`)

| ID | Requirement | Check |
|---|---|---|
| IDET-01 | Header: ID, species, and a whale icon in a random colour, generated on each render and never stored (Q-036). History is the only record tool; there is no Edit or Delete (Q-049). | No icon colour is saved anywhere. |
| IDET-02 | IDs card: every cross-catalog ID (SPLASH, DFO, HappyWhale, NPAC, WGRP, UNAM, UABCS and others), aliases and retired IDs. | |
| IDET-03 | Summary: Sex, Colour Category, First Seen, Last Seen, Sightings, and Dead with the date confirmed. | |
| IDET-04 | A map of every position the whale was seen at. | |
| IDET-05 | Sightings table: Date, Region, Locality, Contributor, Research Group, Sharing Status, Quality, and HappyWhale (a link that opens in a new tab, when present) (Q-055). 50 per page, newest first. Every role sees Private records (Q-034). | Private rows are listed with their status. |
| IDET-06 | Samples table. | |
| IDET-07 | Survey Sightings: the survey sightings where this whale was identified, each opening the sighting. | |

### 4.10 Export (`/export/`)

V1's export stack, kept (Q-017), plus whole gold tables and SQL queries (Q-041, Q-042). Every role (Q-014).

| ID | Requirement | Check |
|---|---|---|
| EXP-01 | Add to Export (on Explore, the lists and record pages) puts a query on a stack kept in the session: the filters or SQL, never rows. The stack holds up to 20 queries, and adding an identical query again does nothing ("Already in Export"). | A 21st add is refused with a message. |
| EXP-02 | Queries card: each query with its label, Efforts and Sightings counts, an "Include the Sightings of These Efforts" or "Include the Efforts of These Sightings" box (on by default), and Remove. Empty: "Nothing to export yet. Use Add to Export on Explore, Efforts or Sightings." | |
| EXP-03 | Sheets card: Efforts, Sightings, Timeline, Weather, Samples, Identifications, Tags, Sighting Events, Other Species. Each has a tick box and row count; Efforts, Sightings, Timeline, Weather and Samples have Choose Columns. Efforts and Sightings are ticked by default. | |
| EXP-04 | Whole Tables card: every gold table with a tick box. Each ticked table becomes one more sheet (Q-041). | Ticking a table adds a sheet with all its rows. |
| EXP-05 | A SQL query sent from the SQL page appears in the Queries card under its name. When the file is built, the server runs that SQL in a read-only DuckDB over the same Parquet files, with a 60-second time limit (Q-057), and the result becomes its own sheet (Q-042). | A write statement is refused; a slow query fails with a message naming the limit. |
| EXP-06 | Preview: tabs for the ticked sheets, 8 rows each, with the true total. | |
| EXP-07 | Download panel: Format (XLSX, CSV zip, GeoJSON zip, GPX, GeoPackage, Parquet zip), Time Zone (UTC or Pacific), Dates (ISO or Excel), and Include the Raw GPS Files of These Efforts (read from the droplet's disk). Formats that cannot hold a sheet say so. | GPX with only a Samples sheet ticked is refused with a message. |
| EXP-08 | Rows matching several queries appear once; with 2 or more queries, a Matched Queries column says which. An XLSX sheet over 1,048,576 rows continues on a second sheet. | |
| EXP-09 | Every download is recorded in the Server event log. | |

### 4.11 SQL (`/sql/`)

Read-only SQL over gold data, run in the browser with DuckDB WASM (Q-006, Q-019). Every role (Q-014).

| ID | Requirement | Check |
|---|---|---|
| SQL-01 | The page loads DuckDB WASM and registers every gold table, served as Parquet to signed-in users only. The Parquet files are refreshed whenever gold data changes; Phase 2 designs how (Q-057). | A signed-out request for a Parquet file is refused. |
| SQL-02 | Layout: a table list (each table's columns and types), a SQL editor, Run, and a results grid showing the first 1,000 rows and the total (Q-057). | `select 1` shows one row. |
| SQL-03 | Only reading is possible; there is no way to change server data from this page. | |
| SQL-04 | Save Query stores a named query's text in a cookie (never results), up to 20 queries per browser, one cookie each, up to 3,500 characters of SQL (a longer query cannot be saved, and the page says why) (Q-057); Saved Queries lists them to open or delete. There is no sharing (Q-012). | A saved query survives a reload in the same browser. |
| SQL-05 | Send to Export puts the named query on the export stack (EXP-05). There is no direct download on this page (Q-042). | The Export count goes up by one. |
| SQL-06 | A SQL error shows DuckDB's message under the editor. | |

### 4.12 Settings (`/settings/`)

| ID | Requirement | Check |
|---|---|---|
| SET-01 | Colour Profile: Cascadia (default) or Generic. | |
| SET-02 | Track display defaults (TRACK-03): Show Points, Show Timeline Events, Show Direction Arrows, Show Path When There Is No Track, Gap After Minutes of Silence, Gap After a Jump of Metres, Gap Above a Speed of Knots, and Gap Style (Dashed Line, Faint Line, Nothing) (Q-043). | |
| SET-03 | Everything except the password is saved in cookies for one year; nothing goes in the database (Q-027). | Saving writes cookies and no database row. |
| SET-04 | Change Password (Django's password change) is on this page for every role. | A Viewer can change their password. |
| SET-05 | Save shows "Settings saved."; an out-of-range number shows a field error (ERR-05). | Minutes 0 is refused. |

### 4.13 Track File Manager (`/tracks/`)

Track Manager and Admin. V1's Track File Manager kept with all its features (Q-017); its map moves onto the track component.

| ID | Requirement | Check |
|---|---|---|
| TFM-01 | Explorer: switch between Track Files and From Positions; file name search; filters for status (Matched, Not Matched, Blank, Deleted), vessel, year and track health. | |
| TFM-02 | Editor: tabs, and the file's text with line numbers for choosing rows. Buttons: Restore, Fill From File, Delete, Revert, Save, Save As Track File. Every line is checked on save; nothing is saved while any line is wrong, and the old version is kept. | A bad line blocks the save and names the line. |
| TFM-03 | Map through the track component at full points (Q-028), with playback, the chosen rows in red, and unsaved points in blue. | |
| TFM-04 | Panels: Track Health (unlikely speed, misordered time, points, time span, distance, average and top speed, gaps, repeated rows), Matched Effort, History (audit entries and earlier versions, which can be loaded). | |
| TFM-05 | Import (one or many CSV files, 25 MB each, 100 MB a batch) with a preview and a suggested effort; Fill From File with a comparison; Change Track File; Match and Unmatch; Create Track From Positions; Delete and Restore. Every action goes through the audit log. | |
| TFM-06 | One track per effort is enforced (Q-008); a second file for the same effort is refused with a message. | |
| TFM-07 | Track checks run after every write and nightly. | |
| TFM-08 | A deleted file is put back by restoring its last version before the delete, so it follows AUD-04 (Q-057, CR-001). | |

### 4.14 Audit Log (`/audit/`, `/audit/<id>/`)

Audit Manager and Admin (Q-021, Q-045).

| ID | Requirement | Check |
|---|---|---|
| AUD-01 | Filters: Record (type and number), Who (each person, plus Pipeline), Change type, date range. | Filtering by Pipeline lists only pipeline entries. |
| AUD-02 | Columns: When, Who, Change, Record, What Changed (first 3 fields), Note. 50 per page with no picker, newest first. Every change is listed, including deletes and restores; nothing is ever removed from the log (CR-001). | |
| AUD-03 | An entry opens in the modal: When, Who, Record (link), Note, a Before and After table, and Removed With It counts for a delete. | |
| AUD-04 | Restore This Version writes a new version that copies the chosen one, with who and why; nothing is deleted (CR-001, replacing Q-044's Undo). Any version can be restored, in any order. Restoring the version before a delete also brings back every record deleted with it. | Restoring the version before a field edit puts the old value back as a new version, and both changes stay in the log. |
| AUD-05 | Any version can be restored, including one written by the pipeline (Q-069, CR-001, replacing Q-046). | A pipeline version has Restore This Version, and restoring it writes a new version by the person. |

### 4.15 Users (`/admin/`)

Admin only (Q-047).

| ID | Requirement | Check |
|---|---|---|
| USER-01 | Django Admin's user pages, styled like the site, showing only Users and Groups. | No survey tables are registered in the admin. |
| USER-02 | The user list shows Username, Name, Email, Roles, Active and Last Login, filterable by role and active. | |
| USER-03 | An Admin can add a user, set their roles (several allowed), set a password and deactivate them. The per-user permissions field and the superuser flag are not shown. | |
| USER-04 | A new user is given the Viewer role (Q-057). | |

### 4.16 Server (`/server/`)

Admin only, in the site's own layout (Q-048).

| ID | Requirement | Check |
|---|---|---|
| SRV-01 | Console of events (sign in and out, failed sign in, exports, audit changes, track checks, 403s, requests slower than 10 s, errors, feedback, deploys, pipeline runs) merged with the web server, database and system logs, newest last, with an Advanced toggle (plain sentences off, full lines on). | |
| SRV-02 | A 24-hour graph of processor, memory and disk use, and facts: uptime, memory, disk free, load, database response time, database connections, database size, last deploy, last pipeline run. | |
| SRV-03 | The page refreshes every 5 seconds. | |
| SRV-04 | Events are kept 180 days and machine samples 7 days. | |

### 4.17 Feedback (`/feedback/`)

| ID | Requirement | Check |
|---|---|---|
| FDBK-01 | Fields: Title (required, up to 200 characters), Details, Type (Bug, Enhancement, Data Problem, Question), Area (Explore, Efforts, Sightings, Individuals, Export, SQL, Track File Manager, Audit Log, Settings, Sign In and Accounts, Other) (Q-051), and up to 3 pictures (PNG, JPEG, GIF or WebP, 5 MB each). | |
| FDBK-02 | Sending opens a GitHub issue with labels for the type and area, with the pictures attached inline through `gh issue create --attach` (Q-056), and shows "Feedback sent. It is issue number N." | A test with a stubbed `gh` receives each picture as an `--attach` argument. |
| FDBK-03 | The site stores no pictures: an upload is held only for the request and removed afterwards, whether sending succeeds or fails (Q-056). | No picture table exists, and no file remains after a send. |
| FDBK-04 | When GitHub is not set up, the page says "Feedback is not set up yet." and shows no form. | |

## 5. Cross-Cutting Behaviour

### 5.1 Record Modal (Q-010)

| ID | Requirement | Check |
|---|---|---|
| MODAL-01 | Efforts, sightings, individuals, edit and delete forms, and audit entries open in a modal built with htmx and the native `<dialog>` element. V1's `modal.js` is not carried over. | |
| MODAL-02 | Opening a record pushes its URL; opening that URL directly shows the same record as a full page with a link back to its list. | Loading `/efforts/<id>/` directly renders a full page. |
| MODAL-03 | Back returns to the previous record opened from a record. Close, Escape and clicking outside close the modal and restore the page URL. | |
| MODAL-04 | Maps inside the modal draw without re-running page scripts by hand. | |

### 5.2 Filters (Explore, Efforts, Sightings)

V1's filter panel, kept (Q-017), with the changes below. The same filters drive the lists, the map, the APIs and the export.

| ID | Requirement | Check |
|---|---|---|
| FILT-01 | Filters: Research Group, Species (sightings only), Vessel, Individual (Explore and Sightings, Q-052), Region, Sub-Area, Locality, Draw an Area, Years, Months, Seasons, Exact Dates, Survey Type, Project or Objective, Tags and Samples, GPS Track, Crew Member, Position Type, Uncertain Species, Sightings on Land, Include Non-Animal Records, Only Efforts With Matching Sightings. | Each filter changes the result count on test data. |
| FILT-02 | Research Group is an ordinary multi-select like Vessel, with CRC selected by default. There is no special chip or separate All box (Q-022). | A fresh visit shows CRC selected; clearing it shows all groups. |
| FILT-03 | Defaults: all years (Q-023), non-animal records excluded, Only Efforts With Matching Sightings on. | A fresh Sightings visit includes every year. |
| FILT-04 | Individual is chosen by typing any whale ID or alias, resolved as in SRCH-02, and keeps only sightings where that whale was identified. | |
| FILT-05 | Each option shows a live count for the current filters. Year and month chips select like a file manager (click, Shift, Ctrl). Each section heading shows how many of its filters are set. | |
| FILT-06 | Apply Filters submits; Reset returns to the defaults. | |
| FILT-07 | Below 768 px wide, the filter panel folds behind a Filters heading that shows how many filters are set; tapping it opens the panel above the results. | At 390 px wide, the list is visible without scrolling past the filters. |

### 5.3 Map (Q-003, Q-031, Q-032)

| ID | Requirement | Check |
|---|---|---|
| MAP-01 | Every map uses MapLibre GL JS with deck.gl layers. No Leaflet. | No Leaflet asset is loaded. |
| MAP-02 | Basemaps: Satellite (Esri World Imagery, default), Map (OpenStreetMap), Ocean (Esri World Ocean Base); overlay Place Names; a scale bar in nautical and metric units. | |
| MAP-03 | Explore opens at latitude 44, longitude -124, zoom 5 unless the URL holds a view. | |
| MAP-04 | Sighting clustering is on by default on Explore, stops at zoom 10, and can be turned off. | |
| MAP-05 | Detail levels: Explore draws tracks simplified to about 550 m; effort and sighting maps draw the stored line, about 11 m; the Track File Manager draws every point (Q-028). | |
| MAP-06 | The site reads GPS points and lines from PostGIS. DuckLake is the source of truth, and PostGIS holds a copy (V2Spec, Q-028). How the copy is kept is designed in Phase 2. | |
| MAP-07 | A failed map data request shows the ERR-02 notice. | |

### 5.4 Track Display (Q-025 to Q-030, Q-054)

| ID | Requirement | Check |
|---|---|---|
| TRACK-01 | One track component draws every track on every map (Explore, effort, sighting, Track File Manager). No page has its own track drawing code. | A code search finds one track module. |
| TRACK-02 | Tracks are one colour, set by the colour profile. A suspect track (implied speed over 40 kn) is always red and dashed (Q-026). | |
| TRACK-03 | User settings: Show Points (thinned on screen), Show Timeline Events (weather readings, log entries and sightings as dots with popups), Show Direction Arrows, and gaps (TRACK-04, TRACK-05). | Each setting changes what is drawn. |
| TRACK-04 | A gap is any step between consecutive fixes that breaks one of three rules: more than N minutes apart (default 30, range 1–240), more than N metres apart (default off, range 50–50,000), or faster than N knots (default off, range 5–100). Defaults match V1 (Q-029, Q-054). | With defaults, a 31-minute silence makes a gap and a 29-minute one does not. |
| TRACK-05 | A gap is drawn as Dashed Line (default), Faint Line or Nothing (Q-030). | |
| TRACK-06 | Gaps are worked out when drawing, from a time on every stored point, so each user's rules apply (Phase 2 keeps the times). | Changing the minutes redraws gaps without reloading data. |
| TRACK-07 | Settings come from Settings (cookie). Each map has a layer panel that flips a setting for that view only, without changing the saved default (Q-027). | Flipping Show Points on a map leaves the cookie unchanged. |
| TRACK-08 | No-Track Path: when an effort has no track file, a dashed line joins its recorded timeline positions in time order. This is a user setting, on by default as in V1 (Q-058). | Turning it off removes the line from an effort with no track. |

### 5.5 History and the Audit Log (Q-018, Q-044, Q-015)

| ID | Requirement | Check |
|---|---|---|
| HIST-01 | One audit log holds every change, by people (edits, deletes, restores, track file actions) and by the pipeline. Each change is a version of the record (CR-001). | |
| HIST-02 | Each version holds the whole record, with when, who (a person or Pipeline), the change type, an optional note, and the change it belongs to. Each changed field's old and new value comes from comparing it with the version before. A delete writes a deleted version of the record and of each dependent under one change (CR-001). This is enough for a later job to write changes back to DB167 (Q-015). | |
| HIST-03 | Every record page has History, which lists every version of that record in time order (the pipeline load, then edits, deletes and restores), with who, when, why, and old and new values. It explains the record's current state (CR-001). Empty: "Nothing has been changed on this record." | |
| HIST-04 | There is no DB167 state, no T-SQL script, and no "Original Database" or "After Cleaning" step (Q-015, Q-018). | |

### 5.6 Global Search (Q-052, Q-053)

| ID | Requirement | Check |
|---|---|---|
| SRCH-01 | The sidebar search box searches record IDs (effort, sighting and sample numbers, whale IDs, aliases, retired IDs, cross-catalog IDs) and names (vessels, localities, species common and scientific). | |
| SRCH-02 | Matching ignores case, spaces, dashes and prefixes, so `crc 1234`, `CRC-1234` and `1234` find the same whale, and tolerates small typos in names using Postgres `pg_trgm`. | `Humpbak` finds Humpback Whale. |
| SRCH-03 | Results appear as you type (from 2 characters, Q-057), grouped by kind, best first, up to 5 per kind. Enter opens the best match. | |
| SRCH-04 | Choosing a record opens it in the modal; choosing a vessel, locality or species opens Sightings filtered by it. | |
| SRCH-05 | No match: "Nothing matches [text]." | |

### 5.7 Empty and Error States (Q-050)

| ID | Requirement | Check |
|---|---|---|
| ERR-01 | A list or search with no rows shows "No [efforts] match these filters." with Reset Filters. | |
| ERR-02 | Map data that fails to load shows a notice on the map, "Could not load the map data.", with Try Again. | |
| ERR-03 | A missing record returns 404 with "No [effort] with ID [N]." and a link to the list. | GET `/efforts/999999999/` returns 404 with that text. |
| ERR-04 | A page the user's roles do not allow returns 403 with "This page needs the [Track Manager] role." and a link home. | |
| ERR-05 | A form error outlines each bad field with its reason under it, and saves nothing. | |
| ERR-06 | A server error returns 500 with "Something went wrong. It has been logged." and records the error in the Server log. | |

### 5.8 Interface Rules

| ID | Requirement | Check |
|---|---|---|
| UI-01 | All headings, page titles, labels, buttons, tabs and column heads are in Title Case. Messages and other sentences are in sentence case. | A test scans templates for lower-case labels. |
| UI-02 | No em dashes anywhere in UI text. | A test scans templates for the em dash character. |
| UI-03 | Labels name the thing, not whose it is ("Settings", not "My Settings"). | A test scans templates for "My " and "Your " in labels. |
| UI-04 | Pages use the site's own components and show restraint: no dashboards or panels not in this spec. | |
| UI-05 | Custom JavaScript stays small; behaviour is done with Django and htmx where possible. Libraries named in this spec are allowed. | |

## 6. Out of Scope

- Public pages of any kind (Q-002).
- Raw-tier tables and raw table export; only gold tables for now (Q-007).
- Writing back to DB167: no DB167 state and no migration script (Q-015).
- The Data Pipeline page and the read-only record pages in the Django Admin (Q-016).
- A dashboard or Cascadia Admin home page (Q-017).
- Editing photo-ID catalog data on the site; it changes only through dbt (Q-049).
- Photo-ID images: Cascadia's own images, and pulling images from HappyWhale (no working API exists). Placeholder icons stand in; OBIS-SEAMAP is a lead for later (Q-036).
- dbt models and combining sources (V2Spec).
- Sharing saved SQL queries, and downloading results from the SQL page directly (Q-012, Q-042).
- Per-user permission grants (Q-013).
- A page-size picker (Q-024).
- Measure tool, Density Layer and Dark Mode (Q-031, Q-052).

## 7. Assumptions

None open. Assumptions A-01 to A-07 and A-09, chosen while writing this spec, were confirmed in Q-057 and are written into the requirements that cite it. A-08 was rejected and became TRACK-08, A-10 was dropped (Q-056), and A-11 was confirmed in Q-058.
