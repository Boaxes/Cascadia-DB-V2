# V1 Inventory

Every page and feature in V1 as committed at `3a637f1` (2026-11-21, `Boaxes/Cascadia-DB` main), what it does today, who uses it, and a proposal for V2. **Every row was confirmed by Brandon on 2026-11-26 (Q-017).** Decisions are in [questions-log.md](../workflow/questions-log.md). An earlier draft was written from a stale copy (`f4b2a36`) and has been replaced (Q-009).

## Access In V1 Today

Defined in `V1/Django/datahealth/access.py` and set up by `manage.py setup_access` on every deploy.

| Role (Django Group) | Permissions | Unlocks |
|---|---|---|
| (any login) | none | Explore, Efforts, Sightings, record pages and history, Settings, Feedback, map APIs |
| Viewer | none | Same as any login |
| Editor | `edit_records`, `delete_records` | Edit and delete efforts and sightings |
| Data Manager | Editor's, plus `export_data`, `access_data_health` | Export; all of Cascadia Admin (Track File Manager, Audit Log with Undo, Data Pipeline); track buttons on effort pages |
| Admin | all six, plus Django's user and group permissions | Django Admin (users, groups, read-only record pages), Server page |

Problems found:

- A Viewer has exactly what a login with no role has. Viewers and Editors cannot export.
- Permissions can also be granted one user at a time in the Django admin, and `is_superuser` bypasses everything, so a user's real access is not visible from their role.
- `manage_users` is defined and never checked.
- Track File Manager writes (delete, restore, save) check only `access_data_health`, while Undo also checks `edit_records`.
- `setup_access` rewrites the role groups on every deploy, so changes made in the admin do not last.
- Only Django Admin users can change their own password.
- Feedback pictures are served without a login.

## Pages And Features

**Who:** Any = any login. DM = Data Manager and above. Admin = Admin role.

### Survey Site (`survey` App)

| # | V1 page or feature | What it does today | Who | Proposal | Reason |
|---|---|---|---|---|---|
| 1 | Login, Logout | Django `LoginView`; logout is a POST from the profile menu | Any | **Keep** | Django built-in |
| 2 | `/` | Redirects to Explore; no home page | Any | **Keep** | Explore stays the landing page (Q-020) |
| 3 | Explore | Filter panel, Leaflet map (clusters, species dots, simplified tracks with dashed gaps), results tabs (first 300 sightings or efforts), Add To Export, measure, draw area, fullscreen, screenshot, resizable side panels | Any | **Change** | MapLibre plus deck.gl (Q-003) with the single track component; show applied filters, which V1 computes but never renders; show an error when a map fetch fails (V1 hides it); the Tracks toggle must hide gap dashes too |
| 4 | Efforts list | 8 columns, sortable, 50 per page, filters, Add To Export, rows open the modal | Any | **Keep** | Restyle into the sidebar layout |
| 5 | Effort detail | Summary, GPS data with start and end sources, map, species seen, extra info, distance check, tracks table with track actions for DM, timeline, history | Any | **Change** | One GPS track per effort (Q-008), drawn by the single track component; drop the duplicate Sub-Area |
| 6 | Sightings list | 9 columns, sortable, 50 per page, filters, Add To Export | Any | **Keep** | Restyle |
| 7 | Sighting detail | Summary, GPS data, map with the effort's track, effort card, extra info, samples, attached records (events, other species, tags, individuals), history | Any | **Change** | Single track component (V1 shows no gaps or suspect style here); individuals identified link to the photo-ID catalog |
| 8 | Edit effort or sighting | Two steps: change fields, then review a From/To table with a reason; writes `dbo` through the audit log | Editor+ | **Keep** | Validate input (V1 lets bad numbers and dates raise errors) |
| 9 | Delete effort or sighting | Lists dependents, hard delete with a full snapshot in the audit log, restorable by Undo | Editor+ | **Keep** | How a delete is stored and reversed is designed in Phase 2 |
| 10 | Record modal (`modal.js`) | Fetches the whole page, lifts out the detail, re-runs its scripts, `pushState`, Back stack, forms post inside | Any | **Change** | Rebuild with htmx and `<dialog>` (Q-010) |
| 11 | Filter panel | Research Group (defaults to CRC), species, vessel, region, sub-area, locality, draw area, years, months, seasons, dates, survey type, objective, tags and samples, GPS track, crew, position type, uncertain, sightings on land, non-animal, matching sightings; live facet counts | Any | **Keep** | Core to the site; audit `filters.js` and `tagpicker.js` line by line |
| 12 | Export stack | Add To Export puts queries (filters, not rows) in a session stack of up to 20; related records on by default | Any | **Keep** | Every role can export (Q-014) |
| 13 | Export page and download | Queries table, 9 sheets with column chooser, 8-row preview, XLSX, CSV zip, GeoJSON zip, GPX, GeoPackage, UTC or Pacific, ISO or Excel dates, raw GPS files in a zip | DM | **Change** | Add whole gold tables (Q-004, Q-007) and queries sent from the new SQL page, which runs in DuckDB WASM (Q-006, Q-019) and saves queries in cookies (Q-012); GPS files come from the droplet's disk |
| 14 | Settings page | One setting: Color Profile (Cascadia or Generic), in a cookie | Any | **Change** | Becomes the one place for display settings, including track display (V1 keeps the track toggles in the Track File Manager's localStorage) |
| 15 | Map JSON APIs | Compact sightings array, simplified tracks GeoJSON, first 300 efforts, one full track | Any | **Change** | Redesigned for MapLibre and deck.gl in the map app's own `urls.py` |
| 16 | Record history dialog | Per field: original DB167 value, after cleaning (with the rule), then each edit | Any | **Change** | Becomes the per-record view of the single audit log; shows only audit log changes, without V1's original and cleaned steps (Q-018) |
| 17 | Glossary tips, tag picker, year/month chips, seasons, page state in the URL, resizable panels | Small UI helpers | Any | **Keep** | Audit each JS file before copying |
| 18 | Colour profiles | Cascadia (per species) and Generic (per group) colours for dots, legend and track | Any | **Keep** | Moves to Settings (row 14) |
| 19 | Feedback | Form that opens a GitHub issue with labels and up to 3 pictures; pictures stored in Postgres forever and served without login | Any | **Keep** | Q-016; pictures served only to signed-in users (Q-002) |
| 20 | Empty database middleware, `make_users`, unused imports and properties, the unused `explore` export kind, dead `missing_file` label, unrendered page-size and sort options | Leftovers | | **Drop** | Not carried over |

### Cascadia Admin (`datahealth` App) And Django Admin

| # | V1 page or feature | What it does today | Who | Proposal | Reason |
|---|---|---|---|---|---|
| 21 | Cascadia Admin home | Three link cards (Data Pipeline, Audit Log, Track File Manager) | DM | **Drop** | The sidebar replaces a menu page (answers Q-011) |
| 22 | Track File Manager | File explorer with filters and health; plain-text editor with line selection; map with gaps, points, timeline events, direction arrows and a playback boat; health, matched effort and history panels; versions; import (single and batch), fill, change file, match and unmatch, create from positions, delete and restore | DM | **Keep** | The real data-quality tool; map rebuilt on MapLibre and deck.gl through the single track component; `track-manager.js` (876 lines) audited line by line |
| 23 | Track checks | Unlikely speed and misordered time per file, re-checked on every write and nightly | DM | **Keep** | Feeds the Track File Manager and suspect styling |
| 24 | Audit Log list, entry, Undo | Human and track changes with filters, Before/After/DB167 table, Undo newest first per record; the entry is deleted when undone | DM | **Change** | One log for human and pipeline changes that answers how a record changed over time (V2Spec); storage designed in Phase 2 |
| 25 | DB167 write-back | `db167_state` on every audit entry, and a downloadable T-SQL script that replays website edits into SQL Server | DM | **Drop** | Q-015: V2 keeps audit entries complete (table, key, old and new values) so a later job can write back |
| 26 | Data Pipeline page | 1,025 lines of hardcoded documentation of the dbt pipeline, dated 2026-10-19 | DM | **Drop** | Q-016; pipeline documentation belongs in the repository when dbt returns |
| 27 | Server page | Console merging app events, nginx, Postgres and journal logs; CPU, memory and disk graph; facts; polls every 5 s. Backed by `ServerEvent` (logins, exports, errors, slow requests) and `ServerSample` | Admin | **Keep** | Q-016; which role sees it is set in the permission table |
| 28 | Django Admin | Users with a Role column and filter, Groups, and read-only pages for 8 survey tables | Admin | **Change** | Keep only users and role assignment; drop the read-only record pages (Q-016); roles only, no per-user grants (Q-013) |
