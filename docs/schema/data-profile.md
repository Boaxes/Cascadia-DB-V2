# Data Profile

What the source data in `Data/` (snapshots of 2026-11-26) looks like, entity by entity, so the gold schema and the synthetic data can be designed from facts. Every number here comes from a named query in [profile_queries.sql](profile_queries.sql) (shown as `query: name`), or from DuckDB's `SUMMARIZE` over each Parquet file (per-column types, ranges, distinct counts and null shares).

## How the Sources Relate

| Source | What it is | Role for V2 |
|---|---|---|
| `SQLServer/dbo` | Raw DB167, the field database that people enter into. | Upstream of everything. Not read by V2. |
| `Postgres/dbo` | DB167 after V1's dbt cleaning: same `*T` table names, rows dropped or merged, hashed `bigint` keys added beside the legacy integer IDs. | The closest thing to "cleaned" for identifications, individuals, research groups and other species. |
| `Postgres/app` | Views and tables over `dbo` that V1's website reads: snake_case columns, typed times, WKT geometry, species and vessels resolved to IDs. | The closest thing to today's gold tier, and the main input for this profile. |
| `MnID/` | The humpback photo-ID catalog, a separate Access database kept by the photo-ID team. | The first catalog. Bm and ErId will follow the same shape. |

Keys: every `app` and cleaned `dbo` row has a hashed 64-bit `id` (unique, query: key_uniqueness) and keeps its DB167 integer as `legacy_*_id` (also unique). Rows link through the hashed IDs (`daily_effort_id`, `sighting_id`, `vessel_id`, `species_id`).

Row counts differ between raw and cleaned because the pipeline drops and merges rows: for example 118,389 sightings in raw DB167 against 114,876 cleaned.

## Summary of Volumes

query: row_counts

| Entity | Rows | Source |
|---|---:|---|
| Sighting | 114,876 | `app.sighting` |
| Daily effort | 25,018 | `app.daily_effort` |
| Daily condition | 53,704 | `app.daily_condition` |
| Daily event | 78,347 | `app.daily_event` |
| Track | 1,570 | `app.track` |
| GPS points | 10,397,499 | sum of `app.track.point_count` (files are not in `Data/`) |
| Sample | 3,102 | `app.sample` |
| Identification | 86,580 | `dbo.IdentificationT` |
| Individual | 11,802 | `dbo.IndividualT` |
| Species | 65 in use (130 in `dbo.SpeciesT`) | `app.species` |
| Vessel | 1,310 | `app.vessel` |
| Research group | 1,093 | `dbo.ResearchGroupT` |
| Event code | 76 | `app.event_code` |
| MnID sighting record | 166,885 | `MnID/mn_id_sightings` |
| MnID individual | 10,743 | `MnID/mn_id_summary` |
| MnID sample | 1,638 | `MnID/mn_id_samples` |
| MnID alias | 815 | `MnID/crc_mn_alias_list` |
| MnID retired ID row | 498 | `MnID/retired_crc_ids` |

The largest table is the GPS points, at about 90 times the sightings. Everything else is small enough for Postgres to hold in memory.

## Daily Effort

One row per vessel per day of survey: the parent of sightings, conditions, events and the track.

- **Keys:** `id` (hashed) and `legacy_daily_effort_id` both unique. The human key is (research group, vessel, date): only 2 pairs repeat (query: effort_natural_key).
- **Dates:** 1950-01-01 to 2026-09-25. Two efforts carry the placeholder date 1950-01-01 (query: date_spans). Effort is seasonal: July and August hold 30% of efforts, and December 3% (query: efforts_by_month).
- **Times:** `start_time` is missing on 42% and `end_time` on 49%, and both are stored as text. Where both are set, a day lasts 2.6 h (10th percentile), 5.9 h (median) and 11.0 h (90th), with a maximum of 18.2 h (query: effort_length).
- **Places:** `region` has 21 values: US West Coast 20,205; British Columbia 3,704; Mexico 618; then a long tail that includes the typo "British Coumbia" (16) (query: region_mix). `sub_area` has 88 values, `locality` 1,091 free-text values, and `launch` and `return_location` around 300 each.
- **Start and end points:** present on only 45% and 42%. They are derived rather than entered: from the Begin (B) and End (T) events, the first positioned record, or the GPS track (`start_coord_source`, `end_coord_source`).
- **Other fields:** `survey_type` (38 values), `project_objective` (175), `personnel` (free text naming people, 6,607 distinct), `survey_comments`, `time_off_effort` and `total_survey_effort` (durations stored as text), and `distance_recorded_nm` (90% null).
- **Children:** 1,398 efforts (5.6%) have no sightings (query: efforts_without_sightings). Per effort there are 3 sightings at the median (90th percentile 10, maximum 118), 4 conditions (maximum 97) and 4 events (maximum 471) (queries: sightings_per_effort, conditions_and_events_per_effort).

## Sighting

One encounter with a group of animals.

- **Keys:** `id` and `legacy_sighting_id` are unique. The human key is (research group, vessel, date, sighting number), and 205 of those repeat as pairs (query: sighting_natural_key). `sighting_number` is free text (15,957 values, such as "-" and "unk6").
- **Sightings without effort:** 923 (0.8%) have no `daily_effort_id` (query: sightings_without_effort). The schema must allow a sighting without an effort.
- **Dates:** 1950-01-01 (2 placeholder rows) to 2026-09-25. By decade: 129 in the 1990s, 14,248 in the 2000s, 77,975 in the 2010s and 22,520 since 2020 (query: sightings_by_decade). The years 2025 (1,632) and 2026 (787) are small because mostly CRC's own data has been loaded so far (query: recent_years_by_group). Sightings peak in July and August (36% between them) and bottom out in December and January (under 3% each) (query: sightings_by_month).
- **Time:** `sighting_time` is missing on 1.4%. 76% of times fall on a whole minute, and 1,168 are exactly 12:00:00, a likely placeholder (query: sighting_time_precision).
- **Position:** `lat`, `lon` and `geom` are missing on 0.8% (903). An end position exists on 22% (25,799) (query: sightings_with_end_position). `position_type` is Precise 79%, Estimated 5%, Calculated 5%, General 3%, or blank 8%.
- **Species:** missing on 404 (0.35%). `species_uncertain` is true on 19. `species_raw` keeps the entered code (122 values).
- **Species mix** (query: species_mix): humpback 32.7%, gray 20.6%, blue 11.4%, common dolphin (unknown subspecies) 6.7%, long-beaked common dolphin 4.4%, fin 3.2%, Risso's 3.1%, bottlenose 3.1%, harbor porpoise 2.1%, then a long tail across 65 species.
- **Group size:** `est_size_best` is null on 5.7%. It depends heavily on species (query: group_size_by_species): the large whales have a median of 1 to 2 and a 99th percentile of 8 to 25, while the common dolphins have a median of 80 to 150, a 99th percentile around 2,000 and a maximum of 11,500. `est_size_min` and `est_size_max` are about 75% null. `num_calves` is 55% null.
- **Research groups:** CRC 27.0%, CINMS 13.9%, AOP 12.1%, BG 8.0%, NB 7.7%, PS 5.2%, then a long tail (query: research_group_mix).
- **Photo fields:** `photos_taken` is true on 53%. `photo_series_1`, `photo_frames_1` and `photographer_1` are free text, about half filled. `identified_individual_count` runs from 0 to 57.
- **Sparse fields:** `bearing` (88% null), `range_m` (95%), `reticle` (96%), `range_source` (91%) and `depth_m` (86%). `group_behavior` (224 values) and `group_type` (786 values) are free text. `comments` is 62% null.
- **Out-of-range values** (query: sighting_value_outliers): 512 groups over 1,000 animals (real, for dolphins); 76 with more calves than animals; 1 depth over 11 km; 111 bearings outside 0 to 360; 2 negative ranges. Some end longitudes fall outside -180 to 180 (minimum -258.18).

## Daily Condition

Sea state readings taken through the day.

- 53,704 rows. Unique `id` and `legacy_daily_condition_id`. 204 have no effort (query: timeline_kinds).
- `condition_datetime` runs from 2001-02-28 to 2026-09-25. Position is missing on 5.3%.
- `beaufort` is 0 to 4 for 95% of rows, mostly 1 and 2. 4 values are over 12 (as high as 32), and 1.6% are null.
- Other outliers: `cloud_cover_pct` over 100 on 16 rows, `swell_ft` out of range on 3, `visibility_nm` over 50 on 31 (query: condition_value_outliers).
- `quality` is a messy code: G, E, F, P, the numbers 1 to 9, and spelled-out words, with 55% null. `precipitation` has 66 free-text values, 48% null.

## Daily Event

Logged events through the day (begin, position, off effort, resume, end).

- 78,347 rows. Unique `id` and `legacy_daily_event_id`. 51 have no effort.
- `event_datetime` runs from 1991-12-07 to 2026-09-25, and position is missing on 2.7%.
- `event_code_id` links to `event_code` (76 codes, but only 25 have a name and description). The most used (query: event_codes_used) are Position P (34,259), Begin B (12,213), End T (10,802), Comment C (5,129), Off Effort O (4,284) and Resume R (4,224).
- `observer_left`, `observer_right` and `recorder` are about 99% null, with around 20 people named.

## Effort Timeline

`app.effort_timeline` is a V1 view, not a table: the union of sightings, conditions and events for one effort, ordered by time (246,927 rows; query: timeline_kinds). V2 can rebuild it as a view.

## Track

One GPS track file per effort day, held in V1's DigitalOcean Spaces bucket (`object_key`, for example `20240914-ROB_tbltGPS.csv`). Cleaned files have exactly three columns: `datetime_utc,latitude,longitude` (V1 `datahealth/gps/tracks.py`). `app.track` holds the metadata, and `app.track_geometry` holds a simplified line built from the file.

- **Rows:** 1,570 tracks, 1,552 of them with points. Every track with a research group is CRC's (15 have none), from 2013-01-04 to 2026-09-14 (query: date_spans).
- **Status** (query: track_status):
  - 1,344 available and usable.
  - 8 available but not usable.
  - 200 unassociated (no effort).
  - 16 blank (no geometry).
  - 2 unresolved.
- **Tracks per effort** (query: tracks_per_effort): 1,307 efforts have one track, 29 have two and 1 has three. The rule is one track per effort (Q-008), so these 30 are data problems for the pipeline to resolve.
- **Efforts with a track:** 1,337 of 25,018, or 1,337 of the 17,237 efforts since 2013 (8%) (query: efforts_with_track). Most efforts never have a track. TRACK-08 draws a path from positioned records instead.
- **`object_key`** repeats on 14 keys (query: track_duplicate_object_keys).
- **Points per track** (query: track_size): 2,026 at the median, 19,389 at the 90th percentile, 38,778 at the 99th and 49,504 at most. That is 10,397,499 in total.
- **Length:** 56 nm at the median, 113 nm at the 90th percentile and 407 nm at most.
- **Fix rate and speed** (query: track_fix_rate_and_speed):
  - Seconds between fixes: 1.2 (10th percentile), 15 (median), 30 (90th).
  - Mean speed: 3.0, 7.3 and 13.5 knots.
  - Duration: 3.8, 8.0 and 11.7 hours.
- **Points by year** run from 50,620 (2025) to 1,489,436 (2017) (query: track_points_by_year).
- **Gaps:** the stored line breaks at every silence longer than V1's gap setting. 993 tracks are one piece, 177 are two, and the rest have 3 to 13 pieces, plus one track with 29 and one with 262 (query: track_geometry_parts).
- **Simplification:** the stored line keeps 17% of the points at the median (1.4% at the 10th percentile, 46% at the 90th). That is 510,926 vertices for all tracks against 10.4 million points (query: track_geometry_vertices).
- **Size:** all 10.4 million points as Parquet with zstd (track ID, time, longitude, latitude) take about 116 MB, or 11 bytes a point. This is measured on invented points at the same volume (query: track_parquet_size_estimate, `scratch/profile/track_size.py`). Real tracks compress better than the random walk used, so this is an upper bound.
- **`track_complete_code`:** "Track Start and End Times ≈ Effort" on 1,046, "Not Recorded" on 312, and 10 other codes. `track_source`: Handheld GPS 823, Tablet 605, Other 63, blank 79.

## Sample

Biopsies, sloughed skin, eDNA and the like.

- 3,102 rows. `legacy_sample_id` is unique.
- `sample_number` is missing on 250, and 14 numbers repeat (2,838 distinct of 2,852 filled) (queries: key_uniqueness, sample_links).
- 22 samples have no sighting. Every sample has an effort.
- Research groups: CRC 2,683, Clark 108, HSU-JKJ 82, SWFSC 77 and others.
- `sample_type` (25 values): Skin and Blubber 1,677, Sloughed Skin 270, eDNA 258, Skin Only Biopsy 179, blank 548.
- `certainty_of_id`: Positive 1,833, Probable 125, Possible 47, blank 1,081.
- `sample_datetime` runs from 2003-02-07 to 2026-09-08. Species, by count: humpback first, then blue and gray.
- MnID has its own sample table (below), with lab results that V1's samples do not carry.

## Identification and Individual (V1)

V1 holds photo-ID for every species in `dbo.IdentificationT` (one row per animal identified in a sighting) and `dbo.IndividualT` (one row per known animal).

- **Identification links** (query: identification_links):
  - 86,580 rows, covering 43,043 sightings.
  - 16,430 (19%) have no individual. Most are records marked ID (8,495), blank (6,208), UF (unmatched fluke, 1,476) or LINK (251) (query: identification_without_individual).
  - 12 have no sighting.
- **Per sighting:** 1 at the median, 4 at the 90th percentile, 150 at most (query: identifications_per_sighting).
- **By species** (query: identifications_by_species):

  | Species | Identifications | Individuals |
  |---|---:|---:|
  | Humpback | 39,133 | 6,915 |
  | Gray | 29,633 | 1,673 |
  | Blue | 13,853 | 2,416 |
  | Fin | 2,317 | 471 |
  | Cuvier's beaked whale | 243 | 130 |

  A few dolphin rows have no individual at all.
- **Sightings per individual:** 2 at the median, 12 at the 90th percentile, 80 at the 99th and 376 at most (query: sightings_per_individual).
- **`IndividualT`:** 11,802 rows with a species and a catalog number (`CRC ID`). Within a species, no catalog number repeats. 3 rows use 0 and 122 have none (query: individual_duplicates). Catalog numbers overlap across species: humpbacks run up to 30092, blues to 5152 and grays to 15263 (query: individuals_by_species). An ID is only unique within its catalog.
- **Catalog matching:** of V1's 6,915 humpback catalog numbers, 6,633 are also in MnID (query: mnid_vs_identification_humpback). The other 282 are retired, aliased or not yet catalogued.
- **Photo columns:** `IdentificationT` also holds photo references (Best Fluke 54% filled, Best Left and Best Right 39%), quality grades (Qual F, L and R, 1 to 4), category, tag fields and match notes. Most are sparse free text.

## Species

- `app.species`: 65 species in use. `category` is cetacean 34, unidentified 17, pinniped 6, other_marine 5 or non_animal 3 (query: species_categories). Each has a `code` (such as Mn, Bm or Er), a common name, and a scientific name (35% blank).
- `dbo.SpeciesT` has 130 rows with order, genus, class and type, including the bird and other species used by `OtherSpeciesT`.

## Vessel

- 1,310 vessels in `app.vessel`, but only 63 carry a legacy vessel ID. The rest were made from free-text vessel names in the source rows. `vessel_number` maps 1,328 spellings to a vessel.
- Of the 1,267 vessels used by an effort, 827 are used once (query: vessels_single_use). The busiest are UNK (2,753 efforts), MD, CE, Condor Express, CH, TR and ZIP (Ziphid) (query: vessel_use).
- Duplicates by spelling are common ("CE" and "Condor Express" are likely one boat). Merging them is pipeline work. The schema only needs a vessel table that can hold aliases.

## Research Group

- `dbo.ResearchGroupT`: 1,093 codes, but only 3 have a full name, and 13 contain spaces (query: research_group_codes). Many are people's names or one-off spellings.
- CRC is the default group (Q-021).
- MnID keeps its own `research_group_contributor_list` (28 groups, with a sharing status of Private or Public).

## Other Species and Tags

- `dbo.OtherSpeciesT` (6,028 rows): birds and other animals counted alongside a sighting. `Class` is Bird 1,734, Mammal 1,670, blank 2,564. 54% have no resolved species.
- `dbo.TagSummaryT` (1,048 rows): tag deployments. 13 of its 45 columns are entirely empty.
- `dbo.SightingEventT` (8,098 rows): reactions and follow events within a sighting, 95% CRC.

The spec shows all three on the Sighting page when present (SDET-07) and exports them as the Tags, Sighting Events and Other Species sheets (EXP-03), so they stay in gold.

## MnID (Humpback Catalog)

MnID is the reference for the catalog model. It has 20 tables. The ones that matter:

### `mn_id_summary`: One Row Per Individual

- 10,743 individuals. `CRC_ID` is unique (1005 to 30104, stored as a double).
- **Other catalogs' IDs** (query: mnid_other_catalog_ids): HappyWhale 2,038, Other 1,110, SPLASH 815, WGRP 388, DFO 355, UABCS 323, UNAM 58. One field can hold two IDs ("HW-Mn0510467; HW-MN0510474").
- `Color_Category` has 26 values. 19 individuals are marked dead, with a free-text date in three formats (query: mnid_dead).
- `Retired_CRC_ID` (6% filled) holds the old numbers folded into this one.

### `mn_id_sightings`: One Row Per Photo-ID Record

- 166,885 records. `CRC_Record` and `PK_MnSightings` are both unique.
- Dates run from 1979-11-30 to 2026-06-17.
- **Records per individual:** 7 at the median, 35 at the 90th percentile, 137 at the 99th and 942 at most (query: mnid_records_per_individual). Only 1 catalog number on a record is missing from the summary (query: mnid_ids_not_in_summary).
- **Sources** (query: mnid_sources): CRC 51,561; then HappyWhale batches (HW2 30,164; HW5 15,800; HW13 15,576 and others), DFO 1,260 and SPLASH 1,496. There are 30 sources in all.
- **Sharing status** (query: mnid_sharing_status): blank 112,788, Public 30,864, Private 23,232, plus one "Privated". Case varies (PUBLIC and Public).
- **Link to CRC sightings:** of the 51,561 CRC records, 34,978 (68%) match a V1 sighting by date and sighting number (query: mnid_to_crc_sightings). There is no stored foreign key: the link has to be built by matching (date, vessel, sighting number), and a third of the records will not match cleanly.
- **Position:**
  - `Dec_Lat` and `Dec_Long` are present on 99.95%. `Lat` and `Long` are the original text ("n35 14.83").
  - `Position_Type` has 20 spellings: PRECISE, Precise, "Precise from field data", GENERAL, APPROX and others.
  - The range is wider than CRC's own data: latitude -62 to 66, with 25 records outside the northeast Pacific (query: geographic_extent).
- **Region:** `Region` (64 values), `Sub-area` (134), `Locality` (10,749 free text), `Loc_Code` (45 codes, 85% filled; query: mnid_location_codes), and `SPLASH_region`. Location codes are defined in `ltloccodes` (66 codes with bounding boxes).
- **HappyWhale columns:** 23 of the 96 columns are `HW_*`: encounter, individual and media IDs, URLs, licence, public flags and submission times. `Record_in_HW?` is true on 77%.
- **Other text columns:** age and reproductive class (AGEREP), genetic sex (Gen_Sex, 0.5% filled), photo quality (24 codes mixing 1 to 3, A to C and others), photographer, roll or file, and frame.

### Aliases and Retired IDs

- **`crc_mn_alias_list`: 815 reconciliations** from an old number to the correct one (query: mnid_alias_shape):
  - 93 have no correct number (retired without a match).
  - 26 point to 0.
  - 7 point to a number that is itself retired, a chain that must be followed to the end.
  - 805 distinct old numbers, so a few old numbers were reconciled twice.
  - Dates are free text in several formats ("01/05/2017", "no info").
- **Old numbers still in use:** 21 still appear as the catalog number on sighting records (query: mnid_alias_old_still_used).
- **`retired_crc_ids`:** 498 rows listing up to four retired numbers each (55 with two, 5 with three, 1 with four) (query: mnid_retired_shape).

### Samples

`mn_id_samples`: 1,638 samples, each `Sample_Number` unique. 1,193 are linked to an individual. There are 12 sources (query: mnid_samples_links). It carries lab results V1 does not: SWFSC and OSU lab IDs, genetic sex and haplotype.

### Working Lists

These are one-off queries and lists saved in Access, not catalog structure. They need no gold table:

- `2024_sample_ids`
- `ids_of_2018_sampled_f`
- `ids_of_ak_seen_in_only_ca`
- `id_late2020_hw_mx`
- `osu_crc_ids`
- `samples_elfes_crc`
- `samples_to_pnnl_2026`
- `hw_records_for_import` (empty)
- `mn_id_sightings_vpre20260304` (an older copy of the sightings)
- `mn_id_excluded_records` (387 pre-2000 records left out of the catalog)
- `useezt` (EEZ flags)

## Quirks the Schema Must Handle

| Quirk | Size | Consequence for the schema |
|---|---|---|
| Sighting without an effort | 923 sightings, 204 conditions, 51 events | `daily_effort_id` is nullable on sightings, conditions and events. |
| Effort without sightings | 1,398 | Nothing required. Lists must not assume children. |
| Effort with more than one track | 30 efforts | One track per effort is a unique constraint. The pipeline picks one, and the extras stay unassociated or are flagged. |
| Track without an effort | 200 unassociated, 2 unresolved | `daily_effort_id` is nullable on tracks. A status column is needed. |
| Track without points | 18 | The track row exists with zero points. |
| Gaps in tracks | 558 tracks with 2 or more pieces | Points keep their times so gaps are worked out at read time (TRACK-03). |
| Placeholder dates and times | 2 sightings and 2 efforts on 1950-01-01; 1,168 sightings at 12:00:00 | Store as given. Flag in data quality, not in constraints. |
| Out-of-range values | Beaufort up to 32, cloud cover up to 1,002%, end longitude -258 | No check constraints on measured values in gold. The pipeline's tests flag them. |
| Free-text times and durations | Effort start and end, time off effort | Gold stores `time` and `interval` types. The pipeline parses, and unparsable values become null. |
| Catalog numbers unique only within a catalog | Humpback, blue and gray ranges overlap | Individual key is (catalog, catalog number). |
| Catalog number 0 or missing | 3 zero, 122 missing | Not a real individual: the pipeline drops them or keeps them unmatched. |
| Aliases and retired numbers | 815 aliases (93 without a target, 7 chains), 498 retired rows | An alias table maps every old number to the current individual. Search resolves through it (SRCH-02). |
| Identifications without an individual | 16,430 | `individual_id` is nullable on identifications (unmatched flukes and links). |
| No stored link between MnID and CRC sightings | 68% match by date and number | Gold stores the link as a nullable `sighting_id` on the catalog record, filled by the pipeline where it matches. |
| Mixed-case categorical codes | Sharing status, position type, region | Gold uses controlled values, normalised by the pipeline. |
| Duplicate human keys | 205 sighting pairs, 2 effort pairs, 14 sample numbers, 14 track file names | Human keys are not unique constraints. Surrogate keys are the identity. |
| Vessels and research groups made from free text | 1,310 vessels (827 used once), 1,093 groups | Lookup tables with a code and a name. The site shows the code. |
