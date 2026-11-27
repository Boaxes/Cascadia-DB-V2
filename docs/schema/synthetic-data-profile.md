# Synthetic Data Profile

What the Phase 4 generator must produce. It fills the gold schema ([schema.sql](schema.sql)) and DuckLake ([ducklake.md](ducklake.md)) with invented data that behaves like the real data. Every figure comes from [data-profile.md](data-profile.md) and the named queries in [profile_queries.sql](profile_queries.sql) (shown as `query: name`).

## Rules

- **Invented, never copied.** No row, ID, name, comment or track from `Data/` is copied. Values are drawn from the distributions below.
  - People's names (personnel, observers, photographers, contributors) come from a name generator.
  - Free text (comments, localities, behaviour) comes from short templates.
  - Localities are invented, but sit in the real sub-areas.
- **Close to the real data in shape.** Volumes, mixes, seasonality and correlations match within about 10%. The generator prints a comparison table against these targets, and a test fails if any target is off by more than 20%.
- **Deterministic.** One seed gives the same data every time, so tests and screenshots are stable.
- **Fills every gold table,** lookups included, and writes points to DuckLake, then writes each `gold.track` version with its `geom` through the same function the site uses (ducklake.md, Write Path).
- **Loads through the pipeline's shape.** Every record arrives as a first version (`change_type = 'load'`) under synthetic pipeline runs, then the history scenarios below add site versions.

## Two Sizes

| Table | Full (performance) | Small (tests) |
|---|---:|---:|
| `daily_effort` | 25,000 | 250 |
| `sighting` | 115,000 | 1,200 |
| `daily_condition` | 54,000 | 540 |
| `daily_event` | 78,000 | 780 |
| `sighting_event` | 8,100 | 80 |
| `other_species` | 6,000 | 60 |
| `tag_deployment` | 1,050 | 20 |
| `track` | 1,570 (1,552 with points) | 20 |
| GPS points | 10,400,000 | about 60,000, including one 49,504-point track |
| `individual` | 16,000 across 3 catalogs and a few other species | 300 |
| `identification` | 253,000 (the upper bound, before survey and catalog records of the same sighting are merged) | 2,500 |
| `sample` | 4,700 | 60 |
| `species` | the 65 real species list (reference data, not personal) | same |
| `vessel` | 1,300 | 30 |
| `research_group` | 1,100 | 15 |
| `event_code` | the 76 real codes (reference data) | same |

Species names and event codes are public reference lists, not records, so the real lists are used. Vessel and research group codes are invented, apart from CRC, which the site defaults to (FILT-02).

## Survey Records

### Efforts

- **Dates:**
  - 1990 to 2026, with yearly counts shaped like `sightings_by_year_recent`: about 1,400 to 1,950 a year from 2011 to 2019, a dip in 2020, and small 2025 and 2026.
  - Months follow `efforts_by_month`: July and August 15% each, December 3%.
  - Two efforts on the placeholder date 1950-01-01.
- **Research group:** CRC on about 27% of sightings' efforts, then a long tail of about 1,100 groups, most used once or twice (`research_group_mix`, `research_group_codes`).
- **Vessels:** 2/3 of vessels used once (`vessels_single_use`), and the 15 busiest carry 56% of efforts (`vessel_use`). One "UNK" vessel holds about 11% of efforts.
- **Places:** region and sub-area mix from `region_mix` and `sub_area_extent`:
  - US West Coast 81%, British Columbia 15%, Mexico 2.5%, and a tail.
  - Southern California 36% and Northern-Central California 16% of efforts.
  - One typo region ("British Coumbia") on 16 efforts.
- **Times:**
  - Start and end time are missing on 42% and 49%.
  - Where both are set, the day lasts 2.6 / 5.9 / 11.0 h (10th, 50th and 90th percentiles), with a maximum of 18 h (`effort_length`).
- **Start and end points:**
  - Present on 45% and 42%.
  - Sources in the real ratios: Begin event 96%, earliest position 3%, GPS track under 1%.
- **Sparse fields:** `distance_nm` 10% filled. Comments 60% filled.

### Sightings

- **Per effort:** 3 at the median, 10 at the 90th percentile, 118 at most. 5.6% of efforts have none (`sightings_per_effort`, `efforts_without_sightings`).
- **Without an effort:** 0.8% of sightings.
- **Time of day** (`sightings_by_hour`): 10:00 to 14:00 holds 53%. Less than 1% fall between 20:00 and 06:00. 1.4% have no time, and 1% are exactly 12:00:00.
- **Species** (`species_mix`):
  - Humpback 33%, gray 21%, blue 11%, common dolphins 13% (three names), fin 3%, Risso's 3%, bottlenose 3%, harbor porpoise 2%.
  - The rest over 55 more species, plus 0.35% with no species (a few of them with a two-species `species_raw` such as "Bm+Bp").
  - 19 marked uncertain.
- **Species by region** (`species_by_region`):
  - British Columbia is mostly gray whale.
  - Mexico is mostly blue whale.
  - The US West Coast follows the overall mix.
- **Group size by species** (`group_size_by_species`): large whales 1 to 2 at the median and up to 25 at the 99th percentile. Common dolphins 80 to 150 at the median, up to about 2,000 at the 99th, and a few over 5,000.
  - `est_size_min` and `est_size_max`: 25% filled, and 76 rows where calves outnumber the group.
  - Some rows where the best estimate falls outside the min and max (SIGHT-01 "Disagrees").
- **Position:**
  - 99.2% have one.
  - Precise 79%, Estimated 5%, Calculated 5%, General 3%, none 8%.
  - End position on 22%.
  - Positions fall inside their effort's sub-area spread (`sub_area_extent`), and at sea except for a few on land (FILT-01 Sightings on Land).
  - 22 positions far outside the northeast Pacific.
- **Sparse fields:** bearing 12%, range 5%, depth 14%, photos taken 53%, comments 38%.

### Conditions and Events

- **Per effort:** 4 conditions at the median (90th percentile 10) and 4 events (90th percentile 13). A few efforts have 97 conditions or 471 events (`conditions_and_events_per_effort`).
- **Beaufort:** 1 and 2 hold 63%, 0 to 4 hold 96%, and four values over 12. Other outliers as in `condition_value_outliers`.
- **Event codes** (`event_codes_used`): P 44%, B 16%, T 14%, C 7%, O 5%, R 5%, then the rest. Most efforts get a B at the start and a T at the end. Events carry positions along the effort's track where it has one.

### Samples, Tags, Sighting Events, Other Species

- **Samples:**
  - On 1.7% of sightings. Skin and Blubber 54%, Sloughed Skin 9%, eDNA 8%, blank 18%.
  - 8% with no sample number, and 14 repeated numbers.
  - A third of the samples are catalog samples with lab results in `extra`, linked to an individual.
- **Tags:** on under 1% of sightings, mostly CRC and OSU.
- **Sighting events and other species:** on about 2.4% and 3.6% of sightings.

## GPS Tracks

- **Which efforts:** only CRC efforts from 2013 on have tracks, about 8% of those efforts (`efforts_with_track`, `crc_share_of_tracked_efforts`), with yearly counts shaped like `efforts_by_year_with_track`.
- **Status:**
  - 1,344 matched and usable, 8 matched but not usable, 200 not matched (no effort), 16 blank (no points), 2 unresolved.
  - 30 efforts with a second or third track file. Only one per effort may be matched (TFM-06); the extras are generated as not matched, with a file name dated to that effort.
- **Points:**
  - 2,026 at the median, 19,389 at the 90th percentile, 49,504 at most.
  - Fixes every 15 s at the median (1 to 30 s from the 10th to 90th percentile).
  - Mean speed 3 / 7.3 / 13.5 kn, and a duration of 3.8 / 8.0 / 11.7 h (`track_size`, `track_fix_rate_and_speed`).
- **Paths:**
  - Each track leaves a harbour in its sub-area, runs a survey pattern offshore (transect legs, loops, and stops at sightings), and returns. The land outline from `gold.land_inland` keeps every point at sea.
  - The sightings of a tracked effort lie on or near its track at their times.
  - Harbours are real public ports in each sub-area (Santa Barbara, Monterey, Anacortes and others), which are places, not records.
- **Gaps and faults** (TRACK-04, TFM-04):
  - About 36% of tracks have one or more silences longer than 30 minutes, matching the split counts in `track_geometry_parts` (1 to 13 pieces, with one track of 29 and one of 262).
  - About 1% of tracks have a step over 40 kn (suspect). This is a chosen figure: V1's suspect count is not in `Data/`.
  - Some tracks have fixes out of time order, and some have repeated rows.
- **File names:** follow V1's form, `YYYYMMDD-VES_source.csv`.

## Photo-ID

- **Catalogs:** three, so IND-04 is exercised:
  - Mn: 10,700 individuals, numbers 1005 to 30104.
  - Bm: 2,400, numbers 1 to 5152.
  - Er: 1,700, numbers 1 to 15263.
  - The number ranges overlap across catalogs, as the real ones do (`individuals_by_species`).
  - About 1,200 more individuals cover fin whales, Cuvier's beaked whales and a few other species, in survey-only catalogs.
- **Identifications:**
  - Per individual: 7 at the median, 35 at the 90th percentile, 942 at most (`mnid_records_per_individual`).
  - 19% have no individual (unmatched flukes and links, `identification_without_individual`).
  - Survey identifications link to sightings of the right species. 68% of CRC catalog records link to a survey sighting, and the rest have `sighting_id` null (`mnid_to_crc_sightings`).
- **Sharing status:** blank 68%, Public 18%, Private 14%.
- **Other IDs:**
  - SPLASH on 8% of individuals, HappyWhale on 19%, DFO on 3%, and a few with two HappyWhale IDs in one field.
  - 815 aliases (93 with no target, 7 chains, 21 old numbers still on records), and about 500 retired numbers.
  - 19 dead, with a date.
- **Sex:** mostly unknown. A minority have a sex, a few of them genetic.

## Edge Cases the Data Must Include

Each is present in both sizes, so tests find it:

| Case | Why |
|---|---|
| Sighting with no effort; condition and event with no effort | Nullable links (SDET-04 empty text) |
| Effort with no sightings, no conditions, no track | Empty states (EDET-06, EDET-09) |
| Effort with no track but 2 or more positioned timeline rows | No-Track Path (TRACK-08), Create Track From Positions |
| Effort with a track that has no points (blank) | Track pill Blank (EFF-01) |
| Track with no effort | Not Matched (TFM-01) |
| Second file for an effort, not matched | TFM-06 |
| Suspect track; track with misordered and repeated fixes | TRACK-02, TFM-04 |
| Track with 262 pieces; the 49,504-point track | Gap drawing and performance |
| Placeholder date 1950-01-01; noon placeholder times | Sorting and display |
| Out-of-range values (Beaufort 32, cloud 1,002%, end longitude -258) | Display must not break |
| Positions on land, and far outside the Pacific | Sightings on Land, map framing |
| Species missing, two-species text, uncertain, unnamed species | SIGHT-01 pills |
| Duplicate human keys (sighting number, sample number, track file name) | Keys are not human keys |
| Catalog number reused across catalogs; alias chain; retired number on a record | SRCH-02, IND-02 |
| Individual with 900+ identifications; with none | IDET paging and empty states |
| Private and Public catalog records | IDET-05 |
| Very long free text and non-ASCII text (accents, emoji) | Layout and export |

## History Scenarios

After the load, the generator writes site versions through the same write path as the site, as invented users:
- 300 edits across efforts and sightings: one field to five fields, half with a note.
- 20 deletes with dependents.
- 5 of those deletes restored.
- 10 restores of an older version.
- 30 track actions: imports, point replacements, match and unmatch, and one delete and restore.
- Two pipeline runs a month apart, so the Audit Log shows Pipeline entries next to people's changes.

In the small size, every scenario appears at least once.

## Not Generated

These come from Django's own setup or from the environment:
- Users and roles: the role migration (decision 006), plus one invented user per role for tests.
- Cookies and sessions.
- The land outline: a public dataset chosen in Phase 4.
