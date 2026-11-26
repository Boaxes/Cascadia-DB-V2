# V1 Inventory

Every page and feature in V1 (`V1/Django`, commit `f4b2a36`), what it does today, who uses it, and a proposal for V2. Proposals marked **Confirmed** have Brandon's answer in [questions-log.md](../workflow/questions-log.md); the rest are proposals until he confirms them.

Who uses it: **All** means any signed-in user. **Staff** means `is_staff` (all four V1 logins today).

## Access In V1

- Every survey page uses `login_required`. Nothing is public. Edit and delete need only a login.
- `/admin/` is not Django's admin site. It is the custom `admintools` app, gated by `is_staff`. Undoing a change lives only there.
- There are no groups and no per-object permissions. `make_users` creates four named staff logins from environment variables.

## Pages

| # | V1 page or feature | What it does today | Who | Proposal | Reason |
|---|---|---|---|---|---|
| 1 | Login `/login/`, Logout | Django `LoginView`; logout is a POST from the profile menu | All | **Keep** | Django built-in; nothing to simplify |
| 2 | Explore `/explore/` (landing page) | Filter panel, full-screen Leaflet map of all sightings and simplified tracks, results sidebar (first 300 sightings or efforts), draw-an-area filter, measure tool, clustering toggle, map state in the URL | All | **Change** | Rebuild the map on MapLibre and deck.gl (Q-003) with the single track component; show the applied filters, which V1 computes but never renders; show an error when a map fetch fails, which V1 swallows |
| 3 | Efforts list `/efforts/` | 8 columns, sortable, 50 per page, full filter panel, opens a row in a modal | All | **Keep** | Works; restyle into the sidebar layout |
| 4 | Effort detail `/efforts/<id>/` | Summary, GPS data, map, species seen, extra info, distance check, tracks table, timeline table, history dialog, record tools | All | **Change** | An effort has exactly one GPS track (Q-008); draw it through the single track component; timeline events become a track setting. The V1 snapshot has 30 efforts with 2 or 3 track records (duplicate rows, or a handheld and a tablet file for one day), which V2 treats as data problems |
| 5 | Sightings list `/sightings/` | 9 columns, sortable, 50 per page, full filter panel | All | **Keep** | Works; restyle |
| 6 | Sighting detail `/sightings/<id>/` | Summary, GPS data, map with the effort's track, effort card, extra info, samples, attached records (events, other species, tags, individuals), history | All | **Change** | Single track component; individuals identified link to the photo-ID catalog |
| 7 | Edit sighting or effort | Two-step form: change fields, review a From/To table with a reason, save; writes `dbo` and the audit log | All (any login) | **Change** | Restrict to the editing role; validate input (V1 lets bad numbers and dates raise errors) |
| 8 | Delete sighting or effort | Confirmation listing dependent rows; hard SQL delete with a JSON snapshot in the audit log; only staff can restore | All (any login) | **Change** | Restrict to the editing role; how a delete is stored and reversed is a Phase 2 audit design question |
| 9 | Detail pages as a modal (`modal.js`) | Fetches the whole detail page, lifts out `#detail`, re-runs its scripts, keeps a back stack, posts forms inside the modal | All | **Change** (asked separately) | About 180 lines of custom JS; htmx or plain pages can do this |
| 10 | Export `/export/` | Choose Explore, Efforts or Sightings (filters remembered in the session), CSV, Excel or GeoJSON, optional zip with GPS track files | All | **Change** | Add whole-table export of gold tables (Q-004, Q-007) and SQL export run in DuckDB WASM (Q-006); how the filtered-list export carries its filters is asked separately |
| 11 | Export download `/export/download/` | Builds the file; R-friendly values; provenance headers; zip pulls track files from object storage | All | **Keep** | Track files come from the droplet's disk in V2, not object storage |
| 12 | JSON APIs `/api/sightings/`, `/api/efforts/`, `/api/tracks/`, `/api/track/<id>/` | Compact arrays and GeoJSON for the Leaflet maps; two levels of track simplification | All | **Change** | Replace with whatever MapLibre and deck.gl need, decided with the map spec; owned by the map app's `urls.py` |
| 13 | Admin dashboard `/admin/` | Four number tiles, sightings per year and efforts by month charts, top species and regions, track coverage, problem counts, last five audit entries | Staff | **Change** (asked separately) | A busy dashboard; keep only what Brandon asks for |
| 14 | Track problems `/admin/tracks/` | Four problem lists (no track file, file missing, unlinked file, lost file) with filters and match counts | Staff | **Keep** | Real data-quality work; moves to the Track Manager role (Q-005) |
| 15 | Track fix pages `/admin/tracks/effort/<id>/`, `/admin/tracks/file/<id>/` | Link, unlink, upload a GPS file; every fix goes through the audit log | Staff | **Keep** | Track Manager role; files live on the droplet's disk in V2 |
| 16 | Audit log `/admin/audit/`, `/admin/audit/<id>/` | List of human edits with filters; one entry in full; Undo, newest first per record | Staff | **Change** | One log for human and programmatic (dbt) changes, reversible (V2Spec); storage is designed in Phase 2 |
| 17 | Record history dialog | Per-field chain: original DB167 value, after cleaning (with rule), each edit | All | **Merge** | Becomes the per-record view of the single audit log |
| 18 | Colour profile (Cascadia, Generic) | Cookie, chosen in the filter panel; colours species dots and the track | All | **Change** | Move to a Settings page beside the track display settings |
| 19 | Glossary tooltips (`{% tip %}`) | Click-to-open `?` bubbles from `glossary.py` | All | **Keep** | Useful; audit the JS and drop unused event tips |
| 20 | Tag picker | Searchable multi-select with species groups, colour dots, counts | All | **Keep** | Core to filtering; audit `tagpicker.js` line by line |
| 21 | Year and month chips, seasons | Shift and Ctrl selection, Clear per row | All | **Keep** | Core to filtering |
| 22 | Page state in the URL | Open filter sections, map view and layers kept with `replaceState` | All | **Keep** | Shareable links |
| 23 | Empty database middleware | Explains an empty local DB in DEBUG | Developers | **Drop** | V2 loads synthetic data in setup |
| 24 | `make_users` command | Creates four named staff logins | Staff | **Drop** | Replaced by the role model and a way to assign roles |
| 25 | Interpolated path (no GPS file) | Dashed line through logged positions when an effort has no track | All | **Change** | Becomes a track setting, part of the single track component |
| 26 | Suspect track (implied speed over 40 kn) | Red dashed line, excluded from map bounds, notice card | All | **Keep** | Part of the single track component |
| 27 | Distance comparison | Recorded nm against GPS length, with a % difference | All | **Keep** | Useful data check on effort detail |
| 28 | Unused code (dead imports, unused `label`, unrendered optional export fields, wrong env var names in the track zip README) | | | **Drop** | Not carried over |

## Track Display Variants In V1

The spec says track display is scattered. These are every variant, which V2 replaces with one component plus user settings.

| Variant | Where in V1 |
|---|---|
| Gap splitting at 30 minutes, stored as a MultiLineString | `admintools/gps/tracks.py` `split_on_gaps()` |
| Simplified to about 11 m in the database | `admintools/gps/tracks.py` `simplify()` |
| Simplified again to about 550 m for Explore | `survey/views.py` `tracks_json()` |
| Explore: solid lines plus dashed gap bridges (the Tracks toggle hides lines but leaves the bridges) | `static/survey/explore.js` |
| Effort detail: solid line, or red dashed when suspect, plus dashed gap bridges, start and end markers | `static/survey/effort-map.js` |
| Effort detail: dashed interpolated path when there is no track | `static/survey/effort-map.js` |
| Sighting detail: solid line, no gaps, no suspect style | `static/survey/sighting-map.js` |
| Raw points: never drawn, only in the export zip | `survey/views.py` `zip_with_tracks()` |
| Timeline events: never drawn, only a table | `templates/survey/effort_detail.html` |
| Colour: one `--track` colour per colour profile | `static/survey/app.css` |
