# How the data was cleaned

The survey data comes from **DB167**, the SQL Server database the Access front
ends write to. Moving it into Postgres involved three kinds of change, and they
are kept apart on purpose.

**Rules** are systematic changes affecting many records, and are not in dispute
— folding spellings that differ only in case, converting a unit, parsing a
number out of a text column. They are what makes the working data different
from the original. There are eight, plus five that clean the GPS files.

**Corrections** are fixes to a handful of records. They are not rules: someone
made a judgement about specific rows. The data pipeline applies each one on
every build from `ETL/dbt/seeds/record_fixes.csv`, which names the record, the
old value, the new value and the reason, and the build stops if a fix finds
nothing. None of them is written to the audit log, which holds only changes
people made on the website. The threshold is 20 records.

**Derived columns** compute values DB167 never had — a map point, a species
link, an effort's position, a track's length. There is no original to compare
them against, so they are neither rule nor correction. Where the derivation
could have gone several ways, the answer is recorded beside it:
`start_coord_source` says, per effort, whether its position came from a log
entry, a GPS track, or an inference.

**Nothing is changed silently.** The original database is kept frozen alongside
the working copy, so every difference between them can be listed, and every
record's page shows its own: what DB167 held, what cleaning made of it, and
every edit since.

---

## The rules

| # | Table | What it does | Records |
|---|---|---|---|
| R1 | five tables | Trim surrounding whitespace and fold case-only spellings into the form used most often in that column | ~14,000 |
| R2 | `SightingT` | Species synonyms: `Zica` to `Zc`, `UD` to `UnDelph`, `Turtle` to `TURT-UN` | 465 |
| R3 | `DailyEffortT` | Survey-type wording: `Non-Standardized Large Vessel` to `Large Vessel Non-Standardized`, `Uknown` to `Unknown` | 77 |
| R4 | `DailyEffortT` | Distance converted to nautical miles from the unit recorded beside it | 2,467 |
| R5 | `SightingT` | Depth converted to metres (feet × 0.3048, fathoms × 1.8288) | 16,091 |
| R6 | `SightingT` | Calf count parsed out of free text. `1?` is an observer who *thinks* they saw one, so it is left empty rather than counted as confirmed | 52,422 |
| R7 | `SightingT`, `DailyEventT` | Coordinate pairs of exactly `(0,0)` cleared. That is a real point in the Gulf of Guinea and never where Cascadia works, so it means the position was not recorded | 320 |
| R8 | `TrackT` | HTML tags stripped from track comments | 584 |

R1 replaces six separate rules in the previous version, which were the same
operation applied to different columns.

### The GPS files

One CSV per day, in whatever state the device left it. These five turn any of
them into one shape: `datetime_utc,latitude,longitude`, UTF-8 with no byte order
mark, LF endings, three columns on every row.

| # | What it does | Scale |
|---|---|---|
| G1 | Ten different header spellings normalised. Columns are matched **by name, never by position** — two files carry an unnamed empty column third, so reading by position pulls the wrong values | 1,479 files |
| G2 | Timestamps normalised: `:00` appended where a device recorded only to the minute, single-digit hours padded. Missing the second case is quietly destructive — every row from midnight on looks malformed, and an afternoon of tracking vanishes out of the middle of a file with no error | — |
| G3 | Rows dropped where the timestamp is blank or impossible, or a coordinate is not a number or out of range | 3,130 rows |
| G4 | Rows dropped where longitude is at or east of zero. Cascadia works from Alaska to Central America and Hawaii, all of it west of Greenwich | 20 rows |
| G5 | The track line built: split wherever the GPS went quiet for more than 30 minutes, then simplified to points about 11 metres apart. Nothing is drawn across a gap — a straight segment bridging an hour of silence is not a path anybody recorded, and that is what used to put tracks across land | 1,482 tracks |

Coordinate text is passed through byte for byte. Reading a coordinate into a
number and writing it back changes the text on a large share of rows.

**These are verified rather than asserted:** running them over the 1,479
original files reproduces all 1,479 cleaned files byte for byte.

---

## Corrections

Each of these is in the audit log with its reasoning, and can be undone there.

| From | What | Records |
|---|---|---|
| GEO-001 | Sub-area spellings merged — `SE Alaska` to `Southeast Alaska` | 15 |
| CND-003 | Quality codes outside E/G/VG/F/P cleared | 14 |
| SAM-001 | Sample types merged — `Skin` to `Skin Only Biopsy` | 12 |
| GEO-F01 | Efforts recorded as US West Coast with an Alaskan sub-area and Alaskan localities | 11 |
| CND-001 | Beaufort values outside 0–12 cleared | 7 |
| LOC-001 | Locality spellings differing by more than case | 5 |
| LOC-002 | `Seiku` to `Sekiu`, the same town with two vowels swapped | 6 |
| TrackT orphans | Tracks naming a vessel that no longer exists, with no vessel text either | 6 |
| CRD-002 | Longitudes outside ±180, unrecoverable, cleared | 2 |
| CRD-003 | A latitude with no longitude, or the reverse | 2 |
| EffortCrewT orphans | Crew rows naming an effort that no longer exists | 2 |
| SAM-003 | Certainty values of `9666666666` and `8` | 2 |
| CRD-F01 | One sighting's longitude sign — `124.8272` is eastern China; the vessel was on the Washington coast | 1 |
| GEO-F02 | One sub-area cleared where it contradicted its own locality | 1 |
| GEO-F03 | One effort set to Mexico — a real trip from San Diego across the border | 1 |

Plus eleven track associations Doug Sandilands made through the old track tool,
recovered under his own name. They had never reached DB167.

---

## Species names

DB167 stores only a code, and says nowhere what one means. The common and
scientific names come from `ETL/seed/species.csv`, a curated list of 65 codes.
Eight of those were ambiguous and three have no name at all, so they show their
code instead. Correcting one is an edit to that file, not a change to any code.

A code with no row in that list keeps its code as its name and is filed as
unidentified rather than being guessed at.

## What was dropped, and why

Rules the previous version applied that are **not** carried over:

| Rule | Why not |
|---|---|
| **Swell readings outside 0–20 feet cleared** | That range was invented. It is not a defined scale, and 23- and 30-foot swells happen offshore. |
| **Survey types grouped by inference** — `adrift` to `Opportunistic`, `Tag Recovery` to `Tagging` | Reads intent rather than fixing a spelling. A judgement about what somebody meant is not data cleaning. |
| **Vessel matching and stub vessels** | The vessel list is built from the records themselves now, so there is nothing left to match or invent. |
| **Multi-species records** — `Bm/p` | "Leave it unlinked" is what happens when nothing matches, not an action. The original text is shown. |
| **Excluding child records that could not be matched** | 626 records were discarded. They are kept now, with their effort link intact and their sighting link empty where it cannot be resolved. |

## One thing to know

The original database is still live: the Access front ends write to it, and its
row counts move from day to day. This copy was taken at a point in time. Between
that moment and this being written, DB167 gained fourteen sightings, an effort,
and two new columns on `SampleT`.
