"""
The new data pipeline, documented as it is built, for readers who do not work
with databases.

Everything the Data Pipeline page says lives here, so the page and the plan
cannot drift apart. The page reads one thing from the database each time it
loads: the tracks that name an Effort DB167 removed (unmatched_tracks). The
value changes (pipeline_fixes.json) and orphans (pipeline_unlinked.json) are
exported from a build of the pipeline (ETL/verify/export_page_data.py); the
other counts were measured on the two copies of DB167 and the live database,
and checked against builds by ETL/verify. Text uses " -> " where an arrow
belongs; the page draws it as an icon.
"""

import json
import pathlib

_HERE = pathlib.Path(__file__)


def _load(name):
    return json.loads(_HERE.with_name(name).read_text())


OVERVIEW = [
    ("1", "raw", "Copy every table from DB167, exactly as it is.",
     "Nothing is changed or left out, so there is always an untouched original to compare against."),
    ("2", "dbo", "Copy the tables the website uses, with real Primary and Foreign Keys and consistent spelling.",
     "The same table names and columns as today's dbo. Tables the website never uses stay in raw."),
    ("3", "app", "Choose what the website shows.",
     "The same views the website reads today, now covering every research group instead of only CRC. "
     "The website shows CRC's records by default, as a filter anyone can change."),
]


# ---------------------------------------------------------------------------
# Step 1: raw
# ---------------------------------------------------------------------------

STEP1 = [
    "Every table in DB167 is copied into raw with its own name, its own columns and its own values. Nothing is "
    "cleaned, merged or left out. After the copy, every column of every table is compared with DB167 to prove "
    "the two match, and raw is then locked so nothing can change it by accident.",
    "raw is a schema in the website's database, as it is today, next to dbo and app.",
]

# Every base table in DB167, with its row count, as of 2026-10-19.
DB167_TABLES = {
    "AdditionalCameraT": 16,
    "AnnualDBT": 18,
    "CollaboratorT": 10,
    "CRC_Vessels_ByYear_T": 323,
    "DailyConditionT": 57136,
    "DailyEffortT": 25018,
    "DailyEffortT_IanDB_SnapshotT": 28228,
    "DailyEventT": 78531,
    "DatabaseFieldT": 364,
    "DatabaseTableT": 12,
    "DataStatusT": 0,
    "DataStatusTypeT": 2,
    "DroneDeploymentT": 7,
    "DroneTargetAnimalT": 0,
    "EffortCrewT": 95,
    "EffortProblemT": 11138,
    "EventCodeT": 25,
    "IdentificationT": 89440,
    "IndividualT": 11802,
    "OtherSpeciesT": 6291,
    "PermitTakeT": 1948,
    "ResearchGroupT": 718,
    "SampleIdentificationT": 1402,
    "SampleT": 3118,
    "ServerSystemT": 1,
    "SightingEventT": 8258,
    "SightingFollowT": 221,
    "SightingIdentificationT": 168330,
    "SightingT": 118380,
    "SightingT_IanDB_SnapShotT": 144400,
    "SourceT": 4,
    "SpeciesT": 116,
    "TagSummaryT": 1048,
    "TrackCompleteCodeT": 13,
    "TrackFileList": 1479,
    "TrackFolderT": 13,
    "TrackingT": 12365,
    "TrackT": 1505,
    "UserT": 7,
    "VesselT": 80,
}

# The tables that go on to dbo: the ones the website reads (through its app
# views or directly on a sighting's page), and the category tables their
# Foreign Keys point at. Every other table stays in raw.
DBO_TABLES = {
    "DailyConditionT", "DailyEffortT", "DailyEventT", "EventCodeT", "IdentificationT", "IndividualT",
    "OtherSpeciesT", "ResearchGroupT", "SampleT", "SightingEventT", "SightingT", "SourceT", "SpeciesT",
    "TagSummaryT", "TrackCompleteCodeT", "TrackT",
}

# What each table holds, for the Step 1 list and each dbo table's entry.
ABOUT = {
    "AdditionalCameraT": "Photos taken during a sighting by extra cameras or photographers: who took them, the "
                         "image series and the first and last frame.",
    "AnnualDBT": "The yearly Access databases that were merged into DB167: year, file name and where it was kept.",
    "CollaboratorT": "Organisations CRC collaborates with, which vessels can belong to.",
    "CRC_Vessels_ByYear_T": "Which vessels CRC used in each year.",
    "DailyConditionT": "Weather and sea conditions, noted several times during each effort: Beaufort sea state, "
                       "swell, cloud cover, visibility, precipitation and the quality of conditions for spotting "
                       "animals.",
    "DailyEffortT": "Efforts: one row per vessel per day per research group, with where it launched and returned, "
                    "the area, the kind of survey, the crew, the times and the distance covered. Almost every other "
                    "record belongs to one of these.",
    "DailyEffortT_IanDB_SnapshotT": "An old copy of the efforts, taken during an earlier attempt to move the data.",
    "DailyEventT": "The day log: timed entries made during an effort, such as leaving port, starting and stopping "
                   "effort, and positions, each with a code from EventCodeT and the observers on duty.",
    "DatabaseFieldT": "Descriptions of DB167's columns, written for the Access forms.",
    "DatabaseTableT": "Descriptions of DB167's tables, written for the Access forms.",
    "DataStatusT": "Periods when a research group's data was in a given state of checking. Empty.",
    "DataStatusTypeT": "The kinds of data status DataStatusT can record.",
    "DroneDeploymentT": "Drone flights made during an effort.",
    "DroneTargetAnimalT": "Animals a drone flight was aimed at. Empty.",
    "EffortCrewT": "Who was on board for an effort.",
    "EffortProblemT": "Problems found when the yearly databases were merged, such as an effort recorded twice or "
                      "under the wrong vessel, and how each was resolved.",
    "EventCodeT": "The list of codes used in the day log, with what each one means.",
    "IdentificationT": "Individual animals recognised in a sighting's photos: which known animal (by its CRC ID) "
                       "was seen in which sighting, with photo details. The website starts reading it for the "
                       "'Individuals Identified' list on each sighting page.",
    "IndividualT": "The catalogue of known individual animals: one row per animal, with its CRC ID and species.",
    "OtherSpeciesT": "Other animals noted alongside a sighting, such as birds or sea lions near a group of whales, "
                     "with a count and a comment. Shown on each sighting's page.",
    "PermitTakeT": "Approaches, biopsies, tags and other 'takes' counted against a research permit, per sighting.",
    "ResearchGroupT": "The list of research groups and organisations whose data is in the database. The category "
                      "table every record's Research Group FK points at.",
    "SampleIdentificationT": "Individual animals identified from a sample.",
    "SampleT": "Samples taken during a sighting, mostly skin and blubber biopsies: what kind, how it was kept, who "
               "took it, the animal's reaction, and the animal it came from when known.",
    "ServerSystemT": "Settings for DB167 itself: its version and backup folder.",
    "SightingEventT": "Things that happened during a sighting, such as close approaches, photo-ID, drone flights, "
                      "tagging and sampling attempts, with the animal's reaction. Shown on each sighting's page.",
    "SightingFollowT": "Focal follows: periods during a sighting when one animal or group was followed.",
    "SightingIdentificationT": "An old copy of sightings joined to the animals identified in them, which DB167 no "
                               "longer updates. The website stops reading it: IdentificationT replaces it.",
    "SightingT": "Sightings: one row each, with the species, time, position, group size and behaviour, calves, "
                 "depth, photos taken and comments. The main record the website shows.",
    "SightingT_IanDB_SnapShotT": "An old copy of the sightings, taken during an earlier attempt to move the data.",
    "SourceT": "The kinds of device a GPS track can come from: tablet, handheld GPS, plotter or other.",
    "SpeciesT": "The list of species codes, with common and scientific names. Today the website builds this list "
                "from a separate list kept by hand; the new process takes it from DB167.",
    "TagSummaryT": "Tags attached to animals during a sighting: the tag number and type, where on the body it "
                   "went, the reaction, and how long it stayed on. Shown on each sighting's page.",
    "TrackCompleteCodeT": "The list of codes describing how complete a GPS track is.",
    "TrackFileList": "An old list of GPS file names. The bucket the files are stored in now decides which files "
                     "exist.",
    "TrackFolderT": "The folders GPS files were kept in, by year.",
    "TrackingT": "Positions and behaviour recorded at intervals while following animals.",
    "TrackT": "GPS track files: one row per file recording a vessel's path during an effort, with the device it "
              "came from and how complete it is.",
    "UserT": "DB167's own user accounts: name, login name and password for each of 7 people.",
    "VesselT": "CRC's list of vessels, with code and name. VesselListT in dbo is built from it.",
}


def tables():
    """[(name, rows, goes to dbo, what it holds)] in DB167's catalog order."""
    return [(name, rows, name in DBO_TABLES, ABOUT[name].split(". ")[0].rstrip(".") + ".")
            for name, rows in DB167_TABLES.items()]


VIEWS_HELP = [
    "DB167 also has 11 views. A view is a saved query: it shows columns from one or more tables without holding "
    "any data of its own. Views are not copied into raw, because raw holds data only; each view's query is "
    "written again for this database and built in dbo, as today. The website reads none of them.",
]

# DB167's views: (view, what it shows, rows in DB167, in dbo, why not).
DB167_VIEWS = [
    ("DailyEffortV", "Each effort with its GPS track file's details. CRC's efforts only, as in DB167.", 3512,
     True, ""),
    ("DuplicateDailyEffortV", "Research group, vessel and date combinations recorded as more than one effort, "
     "with how many.", 0, False, "Added to DB167 on 26 September 2026, after today's dbo was built."),
    ("IdentificationsBySightingV", "Each sighting with the CRC IDs of the animals identified in it, as one list.",
     38630, True, ""),
    ("Mislabelled_IanRecsV", "Merge problems in EffortProblemT next to the matching effort in the old IanDB copy.",
     4074, False, "It reads DailyEffortT_IanDB_SnapshotT and EffortProblemT, which stay in raw."),
    ("SampleEventSightingV", "Each sample with its sighting event and sighting.", 1251, False,
     "Added to DB167 on 28 September 2026, after today's dbo was built."),
    ("SightingEffortTrackV", "Each sighting with its effort and GPS track, for efforts whose track file exists.",
     143826, True, "It reads TrackFileList straight from raw."),
    ("SightingEventSummaryByEffortV", "How many sighting events of each kind each effort had.", 3248, False,
     "Added to DB167 on 1 October 2026, after today's dbo was built."),
    ("SightingV", "Each sighting with its sighting events, other species and samples.", 333161, True, ""),
    ("SpeciesSummaryByEffortV", "How many animals of each species each effort saw.", 46563, True, ""),
    ("TagSummaryV", "Each tag deployment with its sighting's position and species and its effort's place.", 1050,
     True, ""),
    ("TrackV", "Each GPS track with the names of its device type, research group, vessel and completeness code.",
     1505, True, "It reads VesselT straight from raw."),
]


# ---------------------------------------------------------------------------
# Step 2: dbo
# ---------------------------------------------------------------------------

STEP2 = [
    "dbo holds a copy of each table the website uses, with every column. In it, every record gets a real "
    "Primary Key, every reference to another record becomes a real Foreign Key, spellings are made consistent, "
    "and a few useful columns are added, such as a map position or a depth converted to metres. Today's dbo is "
    "built the same way; the rules below say what the new process does differently, and why.",
]

# Every value change, one row per original spelling, as the build made them
# (ETL/dbt/models/build/value_changes.sql, exported by ETL/verify/export_page_data.py).
FIXES = _load("pipeline_fixes.json")["rows"]


def _records(*kinds):
    return sum(f["records"] for f in FIXES if f["kind"] in kinds)


# Orphans, one row per reason, research group and year, from a build of
# today's copy of DB167 (ETL/verify/export_page_data.py). The tracks are not
# in the file: they are read from the database when the page loads.
UNLINKED = _load("pipeline_unlinked.json")
ORPHANS = sum(u["records"] for rows in UNLINKED.values() for u in rows)


def _ranges(numbers):
    """1, 2, 3, 7 -> "1 to 3, 7"."""
    numbers = sorted(numbers)
    out, start = [], None
    for i, n in enumerate(numbers):
        if start is None:
            start = n
        if i + 1 == len(numbers) or numbers[i + 1] != n + 1:
            out.append(str(start) if start == n else f"{start} to {n}")
            start = None
    return ", ".join(out)


def unmatched_tracks(cursor):
    """The tracks that name an Effort which is no longer there, as the rows of
    the orphans table: one per reason, Research Group and year. A track with an
    EffortID but no matched Effort is left unmatched, waiting to be matched."""
    cursor.execute("""
        SELECT t."TrackID", t."Research Group", EXTRACT(year FROM t."SurveyDate")::int, t."EffortID"
        FROM dbo."TrackT" t
        WHERE t.daily_effort_id IS NULL AND t."EffortID" IS NOT NULL""")
    groups = {}
    for track, group, year, effort in cursor.fetchall():
        reason = f"Its effort ({effort}) was removed from DB167; left unmatched, waiting to be matched"
        groups.setdefault((reason, group, year), []).append(track)
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0][1] or "", kv[0][2] or 0, kv[0][0]))
    return [{"reason": reason, "group": group, "year": year, "records": len(ids), "ids": _ranges(ids)}
            for (reason, group, year), ids in ordered]

MERGED = _records("capitals", "spaces", "typo", "synonym", "corrected")
TRIMMED = _records("trim")
EMPTIED = _records("empty")

RULES = [
    {
        "title": "Only the Tables the Website Uses Go on to dbo",
        "text": [
            "16 of DB167's 40 tables go on to dbo: the ones the website reads, and the category tables their "
            "Foreign Keys point at (ResearchGroupT, SpeciesT, EventCodeT, IndividualT, SourceT and "
            "TrackCompleteCodeT). VesselListT, the category table of vessels, is built from VesselT, as today. "
            "The other 24 tables stay in raw, untouched. Today's dbo copies 34.",
            "EffortCrewT is one of the 24. Two of its 95 rows name an effort that DB167 no longer has, so they "
            "belong to nothing. Because the table stays in raw, they never reach dbo, and no rule is needed to "
            "leave them out.",
        ],
        "example": None,
    },
    {
        "title": "A Hashed Primary Key Where DB167's IDs Are Not Stable",
        "text": [
            "In 8 tables, DB167 gives records new ID numbers when data is re-imported. Comparing a copy taken a few "
            "weeks ago with today's shows it: 382 sightings vanished from their IDs, and 277 of them came back "
            "under new ones. The same happened to efforts, day-log entries, weather readings, sighting events, "
            "other species, samples and identifications. Anything that remembers an ID, like an edit made on the "
            "website, would then point at the wrong record or at nothing.",
            "So those 8 tables get a new Primary Key, a column called id, formed from the combination of columns "
            "that identify a record and hashed into one number. For an effort the combination is Research Group, "
            "Vessel and Date. Text is read ignoring capitals and spaces at either end, so 'Zip' and 'ZIP ' are the "
            "same vessel. The same combination always gives the same number, so an effort keeps its Primary Key "
            "however many times it is re-imported. DB167's own ID stays in its column as the Legacy ID, so the "
            "website's addresses, which use it, keep working.",
            "Where records share the whole combination but differ in something else, all are kept: the one with the "
            "lowest Legacy ID keeps the combination's number, and the others add their Legacy ID to it. When DB167 "
            "removes such a duplicate it mostly keeps the lower ID (58 of 82 times between the two copies), so the "
            "record that stays mostly keeps its Primary Key. A record whose combination DB167 changes, for example "
            "a sample number rewritten from ROB-1 to ROB-01, gets a new Primary Key.",
            "Every other table keeps DB167's ID as its Primary Key, as today, because those IDs have never "
            "changed.",
        ],
        "example": "Effort: CRC, ZIP, 15 July 2023 -> always the same id, whatever number DB167 gives it.",
    },
    {
        "title": "Real Foreign Keys",
        "text": [
            "A weather reading belongs to an effort, and a sample belongs to a sighting. In DB167 these references "
            "are only implied: the reading repeats the effort's Research Group, Vessel and Date, and nothing checks "
            "that the effort exists. dbo gives each such table a Foreign Key column (daily_effort_id, sighting_id) "
            "pointing at the parent's Primary Key, filled by matching those same columns, and the database then "
            "refuses any Foreign Key value that points at nothing.",
            "Some records point at an effort or sighting that does not exist (an orphan), usually because the "
            "parent was deleted from DB167 or never entered. These records are kept, with the Foreign Key left "
            f"NULL, and each table below lists exactly which ones they are. {ORPHANS:,} records outside TrackT are in "
            "this position. The tracks that name an Effort DB167 removed are listed under TrackT, read from the "
            "database each time the page loads.",
        ],
        "example": "Weather reading 640 belongs to effort 27051, which was deleted from DB167. The reading is kept, "
                   "with daily_effort_id NULL.",
    },
    {
        "title": "Research Groups and Vessels Get Category Tables",
        "text": [
            "Today the research group and vessel are typed into every record. dbo keeps the typed text and adds a "
            "Foreign Key to one row in the category table of research groups (ResearchGroupT.ResearchGroupID) and "
            "of vessels (VesselListT.vessel_id), so 'Zip' and 'ZIP' are the same vessel, and a vessel's details "
            "live in one place.",
            "ResearchGroupT has not been kept up since 2021, so 375 groups that appear in the data are added to it. "
            "Species and day-log codes get Foreign Keys to their existing category tables (SpeciesT and EventCodeT) "
            "the same way, with missing codes added.",
        ],
        "example": "'Truth' typed as a vessel name gets the Foreign Key of the vessel with code TRH (12,350 "
                   "records).",
    },
    {
        "title": "Spelling Is Made Consistent in Every dbo Column",
        "text": [
            "How depends on the kind of column.",
            "Columns that hold a choice from a set of values (survey type, behaviour, photographer, preservation "
            "and the like): values that differ only in capital letters or spaces become one, and clear typos and "
            "values you asked to merge are merged too. One rule picks the spelling every merge becomes: where the "
            "column has a category table (species, research group, vessel, day-log code), the category table's "
            "spelling; otherwise the existing spelling nearest to Title Case, where each word starts with a capital "
            "or is written all in capitals like an abbreviation, and short joining words such as 'of' may stay "
            "lower case; and between equally near spellings, the most common. Research group, vessel and species "
            "are each one list across every table, so a value is spelled the same wherever it appears. For a typo, only correct spellings "
            "can win. Units of measure keep lower case (m, ft, km), and abbreviated place words are written out "
            "(Pt -> Point). One column is the exception: DailyEffortT's Sub-Area uses the table of corrected "
            "sub-areas Doug Sandilands made, which maps each of its 115 spellings to one of 85 sub-areas. "
            f"{MERGED:,} values change this way. Every change is listed on its column, under 'Table By Table'.",
            "A Primary Key is made from the combination of key columns (see above) as it is spelled once the "
            "rules have run, with one exception: a sample's Sample Type is hashed exactly as DB167 has it. "
            "Merging Sample Type variants (Skin, skin and Skin Only into Skin Only Biopsy, and Sample-Other into "
            "Other; 12 samples) therefore never changes a sample's Primary Key.",
            "Free text (comments, notes, lists of personnel) and identifiers (Field IDs, photo frame numbers, file "
            "names, tag numbers): only spaces at the start and end are removed. Their capital letters are never "
            "changed, because in free text that would alter what someone wrote, and in an identifier the capitals "
            f"can be part of the value. {TRIMMED:,} values change this way.",
            f"In every column: empty text -> NULL ({EMPTIED:,} values).",
        ],
        "example": "Group Beh: 'slow travel' and 'Slow travel' -> 'Slow Travel'. Research Group: 'OrcaNet-StOursC' "
                   "-> 'OrcaNet-StoursC'. A comment 'fluke UP' stays exactly as written.",
    },
    {
        "title": "Exact Copies Are Removed",
        "text": [
            "Some records were imported twice. In the 8 tables with a hashed Primary Key, a record that is "
            "identical to another in every column, apart from its Legacy ID and a note of which import it came "
            "from, is removed, and one copy stays. Records that look alike but differ in anything are all kept.",
        ],
        "example": "3,504 sightings are exact copies, mostly a second import of the 2009 data.",
    },
    {
        "title": "Useful Extra Columns Are Built as Today",
        "text": [
            "dbo adds the same calculated columns today's does: map positions, depth in metres, number of calves "
            "as a number, visibility in nautical miles, distance in nautical miles, each effort's start and end "
            "point, each GPS track's line, length and status, the number of individuals identified in a sighting, "
            "and a short name for each day-log code.",
        ],
        "example": None,
    },
    {
        "title": "Edits Made on the Website Are Kept",
        "text": [
            "People can edit and upload records on the website, and match GPS tracks to efforts. Each change is "
            "written to the site's audit log. Because dbo is rebuilt from raw each time, every change in the audit "
            "log is applied again after the rebuild, finding each record by its hashed Primary Key, so no edit is "
            "lost and none lands on the wrong record when DB167 renumbers.",
            "The audit log holds only changes people made on the website. Every correction the pipeline makes "
            "itself, such as the rules below, is made again on every build and is never written to the audit log.",
            "After each build, every change is checked against DB167 as it was last imported. The Audit Log shows "
            "whether DB167 holds it: Pending, Applied, Conflict (DB167 holds something else) or Not Applicable "
            "(a track file upload, or a value the website works out itself). Once DB167 holds a change, the "
            "rebuild stops applying it again, so it can never overwrite a change made in DB167 since. "
            "The Export SQL Server Migration Script button on the Audit Log page writes every change, in order, "
            "as a script that makes the same changes in DB167. It skips anything DB167 has changed since, and "
            "running it twice changes nothing.",
            "Three entries in the audit log were someone trying the edit form: entry 109 changed sighting 114893 "
            "with no comment, entry 112 deleted it and entry 113 restored it. They are deleted from the log.",
        ],
        "example": None,
    },
    {
        "title": "Day-Log Codes and Species Codes Missing from Their Category Tables Are Added",
        "text": [
            "2,039 day-log entries use 51 codes that EventCodeT does not have: S (1,529 entries), RE (105), OE (72), "
            "SE (57), E (54), ST (44), W (35), SB (28), BO (9), SBT (8), XO (8) and others, mostly from 2004 to "
            "2012, from an older way of keeping the log. A few are mistakes: 0 (5 entries), two codes run together "
            "such as P/O and ET/OE, times typed as codes (P1550, 1715), and Tag-Rec and PB-Ends, which look like "
            "TagRec and PB-End mistyped. All 51 are added to EventCodeT with no description, so every day-log "
            "entry keeps its code and its FK. Descriptions can be written later.",
            "14 species codes that sightings use are added to SpeciesT: UnCet, UnFurSeal, Ship, Boat, Gm, UnPinn, "
            "UnBeak, Meso, Sb, Ziph, Ejap, Pomarine Jaeger, and UW and ULW, CRC's codes for an unidentified whale "
            "and an unidentified large whale.",
        ],
        "example": None,
    },
    {
        "title": "Values That Cannot Be Right Are Cleared",
        "text": [
            "Where a value cannot be true and nothing shows what it should have been, it is cleared (made NULL) "
            "rather than guessed. The rules marked CRC check only CRC's records, because those are the records "
            "that were reviewed.",
            "A position of exactly 0 latitude and 0 longitude was never recorded, so it is cleared from day-log "
            "entries and from the start and end positions of sightings.",
            "A longitude only goes from -180 to 180. CRC's end positions outside that cannot be recovered and are "
            "cleared, latitude and longitude together (2 sightings).",
            "A latitude with no longitude, or a longitude with no latitude, cannot describe a place. A CRC "
            "sighting's start position that has only one of the two is cleared, so neither is kept (2 "
            "sightings). Other research groups' start positions with one value, and end positions with one "
            "value, are left as recorded.",
            "CRC's Beaufort values outside 0 to 12 are cleared (7 weather readings). Some look like transposed "
            "numbers, but none can be recovered reliably. CRC's Quality values other than E, G, VG, F and P are "
            "cleared (14 readings). CRC's Certainty of Sample ID that holds only a number, when it should be "
            "Positive, Probable, Possible, Unknown or Negative, is cleared (2 samples).",
        ],
        "example": "A CRC sighting with a start latitude of 47.9818 and no start longitude has no start position "
                   "at all.",
    },
    {
        "title": "Corrections to Single Records Are Listed in a File",
        "text": [
            "A few mistakes affect only one record or a handful, and no rule can find them. Each is listed in "
            "ETL/dbt/seeds/record_fixes.csv with the record's table, Legacy ID and date, the column, the old "
            "value, the new value, the reason, and a rule code. The build applies a correction only to the record "
            "it names, and only while that record still holds the old value. The build stops if a correction "
            "finds no record, finds a record that no longer holds the old value, changes nothing, or is listed "
            "twice, so a correction can never quietly stop working or change another record.",
            "11 efforts recorded with the Region US West Coast have an Alaskan Sub-Area (Gulf of Alaska or "
            "Southeast Alaska) and an Alaskan Locality (Sitka, Shellikof Bay, Gilmer Bay, Gulf of Alaska or "
            "Southeast Alaska). Their Region becomes Alaska. These are the efforts with Legacy IDs 4535, 4539, "
            "4546, 4548, 4549, 4552, 4554, 4557, 4559, 4561 and 5763. 19 other efforts also pair an Alaskan "
            "Sub-Area with US West Coast and are left as recorded, because a Sub-Area alone does not show which "
            "of the two is wrong, so there is no rule that could change only these 11.",
            "Effort 23015 (29 November 2021) has the Sub-Area Northern Baja California but the Locality Monterey "
            "Bay. Its Region is right and its Sub-Area is wrong, so the Sub-Area is cleared.",
            "Effort 4015 (18 October 2006) is a trip from San Diego into Mexico, and its Sub-Area is Northern Baja "
            "California. Neither Region is wrong, so its Region becomes Mexico to agree with its Sub-Area. This "
            "is a judgement about a real border crossing, so it is listed on its own.",
            "Sighting 114646 (29 June 2005) has a start latitude of 47.045 on the Washington coast and a start "
            "longitude of 124.8272, which is in eastern China. The minus sign was lost, so the longitude becomes "
            "-124.8272.",
        ],
        "example": "Effort 4535 (7 July 2007): Region 'US West Coast' to 'Alaska'.",
    },
    {
        "title": "Tracks with No Vessel Are Left Out",
        "text": [
            "A track whose VesselID names a vessel that VesselT no longer has, and which has no typed Vessel "
            "and no EffortID, has nothing that says whose it is. It is left out of dbo, and so is not shown on "
            "the website or counted. DB167 holds 6 such tracks, all from August 2018, and they stay in raw. A "
            "track that has a typed Vessel, or an EffortID, is kept even if its VesselID names no vessel, with "
            "its vessel found from the typed text.",
        ],
        "example": None,
    },
    {
        "title": "A Track Follows the Effort DB167 Kept",
        "text": [
            "When DB167 removes an effort because it is a copy of another, a track that named the removed effort "
            "would be left unmatched. ETL/dbt/seeds/removed_efforts.csv lists each removed effort and the effort "
            "DB167 kept (their Legacy IDs, and the reason), and a track that names a removed effort has its "
            "EffortID changed to the kept one, so it is matched to that effort. The build stops if a listed kept "
            "effort is missing, or if no track names the removed effort, so a row that does nothing is noticed. "
            "An effort DB167 has put back is used as it is.",
        ],
        "example": "Track 1266 names effort 10015, which DB167 removed as a copy of effort 10016 (same Research "
                   "Group, Vessel, Date and times). It is matched to effort 10016.",
    },
    {
        "title": "A Track's Start Time and End Time Are Converted to UTC",
        "text": [
            "DB167 keeps a track's StartTime and EndTime in Pacific local time (1,403 of its tracks hold exactly "
            "the first time in their file, and 1,413 the last, as Pacific; the others were typed or edited by "
            "hand). The GPS files are in UTC, and so is everything else the website stores and shows. dbo and "
            "app keep these two times in UTC, so the build converts what DB167 holds from Pacific time to UTC, "
            "with daylight saving, as the time zone database gives it. A time somebody typed is converted as it "
            "was typed: it is never replaced by the file's time. Times the website writes (Fill From File, "
            "Import, Save) are the file's own UTC times and are not converted, so a track made on the website "
            "and one from DB167 are in one zone. The Export Tool and the pages convert to Pacific time only "
            "when asked.",
            "Twice a year a Pacific time is not one moment. In the spring the hour from 02:00 to 03:00 does not "
            "exist, and a time in it is read as the hour after. In the autumn the hour from 01:00 to 02:00 "
            "happens twice. For a time in that hour the build looks at the first (for StartTime) or last (for "
            "EndTime) time of the track's file, kept beside its line: if that falls in one of the two hours, it "
            "says which one was meant; otherwise the standard-time (second) reading is used. No track today has "
            "a time in either hour.",
            "The Audit Log keeps these two times in UTC. The SQL Server migration script writes them to DB167 as "
            "Pacific local time, and the check of whether DB167 already holds a change compares them in "
            "Pacific time, so DB167 is always given what it keeps. This is lossy in one hour a year: in the "
            "repeated hour of the autumn change, the two UTC moments 08:30 and 09:30 both become 01:30 Pacific in "
            "DB167, which cannot tell them apart. When DB167 is imported again the build restores each from the "
            "track's file, using the file's first or last time (see above).",
            "A track is matched to an Effort by the Effort's hashed Primary Key, which holds when DB167 renumbers "
            "the Effort. The script gives DB167 the Effort's number as it is now, not the number the Audit Log "
            "kept when the track was matched, so a renumbered Effort keeps its track.",
        ],
        "example": "Track 168: DB167 holds StartTime 2024-09-24 11:22:03. The first point of its file is 2024-09-24 "
                   "18:22:03 UTC. dbo and app hold 2024-09-24 18:22:03.",
    },
]

# The columns that form each hashed Primary Key. (A child's combination
# starts with its parent's.)
KEY_COLUMNS = {
    "DailyEffortT": ["Research Group", "Vessel", "Date"],
    "DailyEventT": ["Research Group", "Vessel", "Date", "EventDateTime", "Code"],
    "DailyConditionT": ["Research Group", "Vessel", "Date", "ConditionDateTime"],
    "SightingT": ["Research Group", "Vessel", "Date", "Sighting"],
    "SightingEventT": ["Research Group", "Vessel", "Date", "Sighting", "EventTime", "SightEvent", "Field ID",
                       "EventID", "Reaction", "SightEventComments", "Dec Lat", "Dec Long"],
    "OtherSpeciesT": ["Research Group", "Vessel", "Date", "Sighting", "Species", "Count", "Comments"],
    "SampleT": ["Research Group", "Vessel", "Date", "Sighting", "Sample #", "Sample Number", "Field ID", "Event",
                "Sample Type", "SampleTime", "Reaction", "Comments"],
    "IdentificationT": ["Research Group", "Vessel", "Date", "Sighting", "IndividualID", "Field ID"],
}

# One entry per dbo table, in DB167's catalog order (the order DBeaver shows),
# then VesselListT, which dbo builds.
#   pk_note    what else to know about the Primary Key
#   duplicates exact copies removed
#   extra      anything else, one paragraph each
ENTRIES = [
    {
        "table": "DailyConditionT",
        "pk_note": "65 readings lost their ID between the two copies of DB167; 46 came back under new ones and "
                   "keep their Primary Key. 14 readings share the whole combination with another but have different "
                   "values; all are kept (rule 2).",
        "duplicates": "3,432 exact copies removed: AOP 2013 (2,391), CRC 2013 (710), CRC 2006 (109), CRC 2001 (60) "
                      "and others (162).",
    },
    {
        "table": "DailyEffortT",
        "pk_note": "Between the two copies of DB167, DB167 renumbered 27 efforts (28143 and 28148 became 29178 "
                   "and 29152), which keep their Primary Key, and removed 84, mostly duplicates of another effort "
                   "with the same Research Group, Vessel and Date. Where it kept the higher ID of such a pair, the "
                   "effort that stayed gets a new Primary Key (24 efforts; rule 2). Two efforts (11953 and 11957) "
                   "have a time of day stored with their date, which makes them match the efforts before them "
                   "(11952 and 11956) once the time is set aside; all four are kept (rule 2).",
        "extra": [
            "Survey types that mean the same thing are merged into one, by the spelling rule: Unk and Unknown; "
            "Non-Standardized Large Vessel and Large Vessel Non-Standardized; Whale Watch Vessel, Whale Watching and "
            "Whale Watch; Line Transect and Vessel Line Transect; Land Observation, Land based, Land Based Ob, Land "
            "Based Survey, Shore and from shore; ENT, Entanglement and Entanglement Response; Kayak and Kayak "
            "Observation. Survey type is a filter on the Explore page, so each of these is now one choice there.",
            "Launch and Return places that are the same place are merged (Drakes Bay and Drake Bay, offshore and "
            "off shore, La Push and LaPush, and others), and their typos are fixed (Monnterey, Porr Angeles, Seiku "
            "for Sekiu, and others).",
            "Locality spellings that differ by more than capitals are merged into the spelling used on the other "
            "efforts: Everett, N Puget Sound into Everett/N. Puget Sound, N Cordell Bank into N. Cordell Bank, and "
            "Pt. St.George and Pt. St. George into Pt St George (5 efforts).",
            "Region follows the Sub-Area for 12 efforts and a wrong Sub-Area is cleared for 1. These are "
            "corrections to single records, listed in a file (see rule 11 above).",
            "Sub-Area takes Doug Sandilands's corrected names (Django/survey/sub_areas.csv), which also give their "
            "order from north to south. The website's Sub-Area filter already uses the same table, so it lists "
            "each corrected sub-area once, north to south, and matches every spelling under it.",
            "Project/Objective has its own list of spellings in the spelling rule, and 9 typos are fixed "
            "(Opportunstic for Opportunistic, TagRecovery for Tag Recovery, Bm Fliming for Bm Filming, and others). "
            "8 more pairs are different wordings of the same project and are merged into the fuller or more common "
            "wording: SOCAL12-Leg 1 into SOCAL12-Leg I, WA-OR Sect 6 into WA-OR Section 6, Stanford Drone Ops into "
            "Stanford Drone Operations, Marine Vib into Marine Vibraseis, CRC-DFO tagging into CRC/DFO Tagging "
            "Project, WW into Whale Watch, not entered into Unk, and Entanglement into Entanglement Response. "
            "Projects that only look alike are kept apart, such as SOCAL10 and SOCAL11, Whale Watch and Whale "
            "Watch-CRC, and Stanford and Stanford-IOS. "
            "Project/Objective is a filter on the Explore page, so each project is one choice there.",
            "5 CRC efforts record a distance between 60.6 and 92.7 with the unit m. They are taken as recorded, in "
            "metres, as today.",
        ],
    },
    {
        "table": "DailyEventT",
        "pk_note": "107 entries lost their ID between the two copies of DB167; 77 came back under new ones and "
                   "keep their Primary Key. 18 entries share the whole combination with another but differ, mostly "
                   "CRC 2006 entries imported twice, one with a comment; all are kept (rule 2).",
        "duplicates": "184 exact copies removed: CRC 2022 (107), CRC 2006 (63), AOP 2014 to 2015 (14).",
    },
    {
        "table": "EventCodeT",
        "extra": ["The 51 codes the day log uses but this table lacks are added as new rows, with no description "
                  "(see rule 9 above)."],
    },
    {
        "table": "IdentificationT",
        "pk_note": "457 identifications lost their ID between the two copies of DB167: 223 came back under new "
                   "IDs and keep their Primary Key, 19 came back with a changed IndividualID or Field ID and get a "
                   "new one, and 215 were removed. 553 identifications share the whole combination with another but "
                   "differ in other details, such as photo quality; all are kept (rule 2).",
        "duplicates": "2,860 exact copies removed.",
        "extra": [
            "A sighting's page lists the individual animals identified in it. Today that list comes from "
            "SightingIdentificationT, a copy that DB167 stopped updating: it is missing the 807 sightings and 466 "
            "identifications added since, still lists 370 identifications for sightings that were deleted and 351 "
            "for identifications that were deleted, and has 73,232 empty placeholder rows, which make 19,735 CRC "
            "sightings show '1 individual identified' when none was. The list, and the count, now come from "
            "IdentificationT and IndividualT, which hold the same animal IDs, Field IDs and species and are "
            "current. SightingIdentificationT stays in raw.",
        ],
    },
    {"table": "IndividualT"},
    {
        "table": "OtherSpeciesT",
        "pk_note": "25 records lost their ID between the two copies of DB167. DB167 re-imported its 2026 records "
                   "with the species written as a class (ALC-CA became Bird) and some counts changed, so 23 came back "
                   "as new records with a new Primary Key, and 2 were removed. 49 records share the whole "
                   "combination with another but differ elsewhere; all are kept (rule 2).",
        "duplicates": "263 exact copies removed.",
    },
    {
        "table": "ResearchGroupT",
        "extra": [
            "Every group in ResearchGroupT was first used by 7 December 2021; no group that started sending data "
            "after that was ever added. The 375 missing groups, which account for 68,202 records in the tables "
            "that go on to dbo (for example CINMS 36,213, NB 23,983, Opp-Nblack 2,477 and STAP 1,415), are added "
            "as new rows with their code only and new ResearchGroupIDs above the highest, in code order.",
        ],
    },
    {
        "table": "SampleT",
        "pk_note": "15 samples lost their ID between the two copies of DB167. DB167 re-imported its 2026 samples "
                   "with their numbers written differently (CRC-20260508-ROB-1 became CRC-20260508-ROB-01) and times "
                   "added, so 7 came back as new records with a new Primary Key, and 8 were removed. 20 samples "
                   "share the whole combination with another but differ elsewhere; all are kept (rule 2).",
        "duplicates": "16 exact copies removed.",
        "extra": [
            "Sample Type variants that mean the same thing are merged: Sample-Other into Other (3 samples), and "
            "Skin, skin and Skin Only into Skin Only Biopsy (9 samples). The eleven one-off field notes, such as "
            "'mud? From antenna area', are kept as written rather than forced into a category. A sample's "
            "Primary Key is made from the Sample Type exactly as DB167 has it, so these merges do not change it.",
        ],
    },
    {
        "table": "SightingEventT",
        "pk_note": "The combination is this long because before 2026 the time was never filled in. Its time is "
                   "EventTime: EventDateTime, which DB167 gained in 2026, is only Date and EventTime together, and "
                   "would have given every event a new Primary Key the day it appeared. 19 events lost their ID "
                   "between the two copies of DB167: DB167 re-imported its 2026 events with positions rounded to 4 "
                   "decimals, so 12 came back as new records with a new Primary Key, and 7 were removed.",
        "duplicates": "160 exact copies removed.",
    },
    {
        "table": "SightingT",
        "pk_note": "382 sightings lost their ID between the two copies of DB167; 277 came back under new ones, "
                   "72 of them with a different DailyEffortID, and keep their Primary Key. 410 sightings share the "
                   "whole combination with another but differ; all are kept (rule 2).",
        "duplicates": "3,504 exact copies removed, mostly a second import of the 2009 data (IDs 104659 to 108739).",
        "extra": [
            "8 sightings whose DailyEffortID is 26998, an effort deleted as a copy of effort 3979, get the FK of "
            "3979, found by Research Group, Vessel and Date.",
            "Zc, zc and Zca get the species FK of California sea lion, and Zica stays Cuvier's beaked whale. Today's "
            "process changes every Zica to Zc and treats Zc as Cuvier's beaked whale, but the 46 sightings recorded "
            "as Zc in DB167 are sea lions: their comments say 'Hauled on NOAA weather buoy', '80 Bulls', a herd of "
            "1,200.",
            "Ddc (146 sightings) and Ddd (38), the two common dolphin types written as subspecies in 2004 and 2005, "
            "get the species FKs of Dc and Dd. Species text that matches no code in SpeciesT keeps its text with the "
            "species FK NULL: NA (64), CINMS's mark for non-target animals; two species in one, such as Bm+Bp (8); "
            "Bb and BB (10); Unk, unknown, UnID and MM (12); DO, LP, Li, DP, NP, Dl and Lc (15).",
        ],
    },
    {"table": "SourceT"},
    {
        "table": "SpeciesT",
        "extra": ["14 codes that sightings use are added as new rows (see rule 9 above)."],
    },
    {
        "table": "TagSummaryT",
        "pk_note": "No tag record has ever lost or changed its ID.",
    },
    {"table": "TrackCompleteCodeT"},
    {
        "table": "TrackT",
        "pk_note": "No track has ever lost or changed its ID.",
        "extra": [
            "As today, a file in the bucket with no TrackT row gets one, waiting to be matched to an effort (15 "
            "today), and uploading a file on the website draws its line on the map. Its TrackID is kept with the "
            "file, so it stays the same however many tracks DB167 gains; today it is numbered on from DB167's "
            "highest TrackID each time, which would move it, and any match made to it, onto another file.",
            "Four tracks were matched to efforts that no longer exist. 1592 and 1588 are matched to efforts 29178 "
            "and 29152, which DB167 renumbered from 28143 and 28148, and 1266 to effort 10016, which has the same "
            "date, vessel and times as the removed 10015 (see rule 13 above). 1336 stays unmatched, waiting to be "
            "matched: its effort 13592 was removed, and the nearest, 26856, has different times.",
            "6 tracks are left out of dbo because they name a vessel that VesselT no longer has and have no typed "
            "Vessel and no EffortID (see rule 12 above).",
            "StartTime and EndTime are converted from DB167's Pacific local time to UTC (see rule 14 above).",
        ],
    },
    {
        "table": "VesselListT",
        "about": "The category table of vessels, built by dbo (it is not in DB167). One row per vessel: every "
                 "vessel in VesselT, and every vessel typed in the data that VesselT does not have. Every record's "
                 "Vessel FK points at it.",
        "pk_note": "Keeps today's vessel_id numbers; a vessel new to the table gets the next number.",
    },
]

# Columns dbo adds, per table: (column, "fk" for a Foreign Key or "today" for
# a calculated column today's dbo also has). The hashed Primary Key is not
# listed here; it always comes first.
ADDED = {
    "DailyConditionT": [("daily_effort_id", "fk"), ("research_group_id", "fk"), ("vessel_id", "fk"),
                        ("geom", "today"), ("visibility_nm", "today")],
    "DailyEffortT": [("research_group_id", "fk"), ("vessel_id", "fk"), ("total_distance_nm", "today"),
                     ("start_point", "today"), ("end_point", "today"), ("start_coord_source", "today"),
                     ("end_coord_source", "today")],
    "DailyEventT": [("daily_effort_id", "fk"), ("research_group_id", "fk"), ("vessel_id", "fk"),
                    ("event_code_id", "fk"), ("geom", "today")],
    "EventCodeT": [("name", "today")],
    "IdentificationT": [("daily_effort_id", "fk"), ("sighting_id", "fk"), ("research_group_id", "fk"),
                        ("vessel_id", "fk"), ("species_id", "fk")],
    "IndividualT": [("species_id", "fk")],
    "OtherSpeciesT": [("daily_effort_id", "fk"), ("sighting_id", "fk"), ("research_group_id", "fk"),
                      ("vessel_id", "fk"), ("species_id", "fk")],
    "SampleT": [("daily_effort_id", "fk"), ("sighting_id", "fk"), ("sighting_event_id", "fk"),
                ("research_group_id", "fk"), ("vessel_id", "fk"), ("species_id", "fk")],
    "SightingEventT": [("daily_effort_id", "fk"), ("sighting_id", "fk"), ("research_group_id", "fk"),
                       ("vessel_id", "fk")],
    "SightingT": [("daily_effort_id", "fk"), ("research_group_id", "fk"), ("vessel_id", "fk"), ("species_id", "fk"),
                  ("identified_individual_count", "today"), ("geom", "today"), ("end_geom", "today"),
                  ("num_calves", "today"), ("depth_m", "today"), ("species_uncertain", "today")],
    "SpeciesT": [("category", "today")],
    "TagSummaryT": [("daily_effort_id", "fk"), ("sighting_id", "fk"), ("research_group_id", "fk"),
                    ("vessel_id", "fk")],
    "TrackT": [("daily_effort_id", "fk"), ("vessel_id", "fk"), ("geom", "today"), ("length_nm", "today"),
               ("point_count", "today"), ("track_status", "today"), ("file_name", "today")],
}

# Each Foreign Key column dbo adds: (the Primary Key it points at, the columns it is found by).
FOREIGN_KEYS = {
    "daily_effort_id": ("DailyEffortT.id", "Research Group, Vessel and Date"),
    "sighting_id": ("SightingT.id", "Research Group, Vessel, Date and Sighting"),
    "sighting_event_id": ("SightingEventT.id", "SightingEventID"),
    "research_group_id": ("ResearchGroupT.ResearchGroupID", "Research Group"),
    "vessel_id": ("VesselListT.vessel_id", "Vessel"),
    "species_id": ("SpeciesT.SpeciesID", "Species"),
    "event_code_id": ("EventCodeT.EventCodeID", "Code"),
}
# Foreign Keys today's dbo already has, besides vessel_id.
TODAY_FK = {("SightingT", "species_id"), ("SampleT", "species_id"), ("OtherSpeciesT", "sighting_id"),
            ("SightingEventT", "sighting_id"), ("DailyEventT", "event_code_id")}

CALCULATED = {
    "geom": "Its position, ready to draw on the map",
    "end_geom": "Where the sighting ended, ready to draw on the map",
    "visibility_nm": "Visibility in nautical miles",
    "total_distance_nm": "Distance covered, in nautical miles",
    "start_point": "Where the effort started, on the map",
    "end_point": "Where the effort ended, on the map",
    "start_coord_source": "Where the start point came from: a day-log entry, a GPS track or an estimate",
    "end_coord_source": "Where the end point came from: a day-log entry, a GPS track or an estimate",
    "name": "A short display name for the code",
    "identified_individual_count": "How many individual animals were identified, from IdentificationT",
    "num_calves": "Number of calves, as a number",
    "depth_m": "Depth in metres",
    "species_uncertain": "Whether the observer marked the species as uncertain",
    "category": "Whale, dolphin, bird, and so on, from Class",
    "length_nm": "Length of the track in nautical miles",
    "point_count": "Number of GPS points in the file",
    "track_status": "Whether the file is stored and whether it is matched to an effort",
    "file_name": "The file's name in the bucket",
}
CALCULATED_TYPE = {"geom": "Map Point", "end_geom": "Map Point", "start_point": "Map Point", "end_point": "Map Point",
                   "start_coord_source": "Text", "end_coord_source": "Text", "name": "Text", "category": "Text",
                   "species_uncertain": "Yes or No", "track_status": "Text", "file_name": "Text",
                   "num_calves": "Whole Number", "identified_individual_count": "Whole Number",
                   "point_count": "Whole Number"}

# Existing columns whose role changes: (table, column) -> change.
COLUMN_ROLE = {}
for _t in ("DailyConditionT", "DailyEventT", "IdentificationT", "OtherSpeciesT", "SampleT", "SightingEventT",
           "SightingT", "TagSummaryT"):
    COLUMN_ROLE[(_t, "DailyEffortID")] = ("Kept as a value only. Today it is the FK to DailyEffortT.DailyEffortID; "
                                          "daily_effort_id is the FK now")
for _t in ("IdentificationT", "SampleT"):
    COLUMN_ROLE[(_t, "SightingID")] = ("Kept as a value only. Today it is the FK to SightingT.SightingID; "
                                       "sighting_id is the FK now")
    COLUMN_ROLE[(_t, "IndividualID")] = "FK to IndividualT.IndividualID, as today"
COLUMN_ROLE[("SampleT", "SightingEventID")] = ("Kept as a value only. Today it is the FK to "
                                               "SightingEventT.SightingEventID; sighting_event_id is the FK now")
COLUMN_ROLE[("TrackT", "EffortID")] = ("Kept as a value only. Today it is the FK to DailyEffortT.DailyEffortID; "
                                       "daily_effort_id is the FK now")
COLUMN_ROLE[("TrackT", "ResearchGroupID")] = "FK to ResearchGroupT.ResearchGroupID, as today"
COLUMN_ROLE[("TrackT", "TrackCompleteCodeID")] = "FK to TrackCompleteCodeT.TrackCompleteCodeID, as today"
COLUMN_ROLE[("TrackT", "SourceID")] = "FK to SourceT.SourceID, as today"
COLUMN_ROLE[("TrackT", "VesselID")] = ("Kept as a value only. Today it is the FK to VesselT.VesselID; VesselT stays "
                                       "in raw, so vessel_id is the FK now")

# Every raw table's columns and types, in DB167's order. See the file.
COLUMNS = _load("pipeline_columns.json")
COLUMNS["VesselListT"] = [["vessel_id", "integer"], ["code", "text"], ["name", "text"],
                          ["legacy_vessel_id", "integer"]]
VESSEL_LIST_COLUMNS = {
    "vessel_id": "Primary Key",
    "code": "The vessel's code: VesselT's VesselCode, or the spelling typed in the data for a vessel VesselT "
            "does not have",
    "name": "VesselT's VesselName, where it has one",
    "legacy_vessel_id": "VesselT's VesselID, where it has one",
}

TYPE_LABEL = {"text": "Text", "integer": "Whole Number", "smallint": "Whole Number",
              "double precision": "Decimal Number", "boolean": "Yes or No", "date": "Date",
              "time without time zone": "Time", "timestamp without time zone": "Date and Time", "bytea": "Binary"}


def _quote(value):
    return value if value.startswith("(") else f"'{value}'"


def _condense(fixes):
    """Every value change to one column, one line per resulting value."""
    lines, merges = [], {}
    for f in fixes:
        if f["kind"] in ("capitals", "spaces", "typo", "synonym", "corrected"):
            merges.setdefault(f["to"], []).append(f)
    for target, group in sorted(merges.items(), key=lambda kv: -sum(f["records"] for f in kv[1])):
        sources = ", ".join(f"{_quote(f['from'])} ({f['records']:,})" for f in group)
        lines.append(f"{sources} -> {_quote(target)}")
    for f in fixes:
        if f["kind"] == "empty":
            lines.append(f"Empty Text ({f['records']:,}) -> NULL")
        elif f["kind"] == "trim":
            lines.append(f"Spaces at the Start or End ({f['records']:,}) -> Removed")
    return lines


def primary_key(table):
    """(the Primary Key sentence, the PK column, the Legacy ID column or None)."""
    first = COLUMNS[table][0][0]
    if table in KEY_COLUMNS:
        cols = ", ".join(KEY_COLUMNS[table])
        return (f"The Primary Key, id, is formed from the combination of ({cols}), hashed into one number. "
                f"{first} is kept as the Legacy ID.", "id", first)
    if table == "VesselListT":
        return "The Primary Key is vessel_id.", "vessel_id", None
    return f"The Primary Key is {first}, DB167's own ID, as today.", first, None


def column_rows(table, fixes):
    """[(column, label, type, [changes])] for every column dbo has for this table, Primary Key first."""
    by_column = {}
    for f in fixes:
        by_column.setdefault(f["column"], []).append(f)
    _, pk, legacy = primary_key(table)
    rows = []
    if table == "VesselListT":
        for column, kind in COLUMNS[table]:
            label = " (Primary Key)" if column == pk else ""
            rows.append((column, label, TYPE_LABEL[kind], [f"New: {VESSEL_LIST_COLUMNS[column]}"]))
        return rows
    if legacy:
        rows.append(("id", " (Primary Key)", "Whole Number",
                     [f"New: a hash of ({', '.join(KEY_COLUMNS[table])})"]))
    for column, kind in COLUMNS[table]:
        label = " (Legacy ID)" if column == legacy else " (Primary Key)" if column == pk else ""
        changes = []
        if (table, column) in COLUMN_ROLE:
            changes.append(COLUMN_ROLE[(table, column)])
        changes += _condense(by_column.get(column, []))
        rows.append((column, label, TYPE_LABEL.get(kind, kind), changes))
    for column, how in ADDED.get(table, []):
        if how == "fk":
            target, source = FOREIGN_KEYS[column]
            if column == "vessel_id" or (table, column) in TODAY_FK:
                change = f"FK to {target}, found by {source}, as today"
                if (table, column) in {("OtherSpeciesT", "sighting_id"), ("SightingEventT", "sighting_id")}:
                    change = f"FK to {target}, found by {source}. Today it points at SightingT.SightingID"
            else:
                change = f"New: FK to {target}, found by {source}"
            if (table, column) == ("TrackT", "daily_effort_id"):
                change = ("New: FK to DailyEffortT.id, set when a person matches the track to its effort "
                          "(see below)")
            if (table, column) == ("SampleT", "sighting_event_id"):
                change = "New: FK to SightingEventT.id, found from SightingEventID"
            rows.append((column, "", "Whole Number", [change]))
        else:
            rows.append((column, "", CALCULATED_TYPE.get(column, "Decimal Number"),
                         [f"Added, as today: {CALCULATED[column]}"]))
    return rows


TRACK_HELP = [
    "GPS track files are stored in an online bucket, one file per vessel per effort. TrackT has one row per file. "
    "A person matches each file to its effort on the website; nothing is matched automatically. When a file is "
    "shown, every effort on the same date is offered, and when an effort is shown, every unmatched file from that "
    "date is offered.",
    "Each track has a status: available (matched, and the file has points), blank (matched, but the file has "
    "no points yet), unassociated (stored, but not matched) or unresolved (neither). A track the data names but "
    "the bucket does not hold gets a blank file, with the header and nothing else, from "
    "manage.py create_blank_track_files, so that every track can be opened and filled from a file in the Track "
    "File Manager. Importing, saving, filling, matching, unmatching, deleting and restoring a track file are "
    "recorded in the audit log, so they are re-applied after every rebuild. A match is stored as the Foreign "
    "Key daily_effort_id, pointing at the effort's hashed Primary Key, so it survives DB167 renumbering the "
    "effort.",
    "An effort has one track file at most. The website will not match a second file to an effort, import one "
    "for it or add one, and the build stops if any effort other than the 31 listed in "
    "seeds/multi_track_efforts.csv has more than one. Those 31 had two or three before the rule, keep what "
    "they have, and can have them edited, unmatched or deleted, but not added to. DB167 holds only the names "
    "of track files, never the files, so the files are only in the bucket.",
]

TRACK_STATES = [
    ("Fine", "Matched to an effort, and the file has points", "1,309"),
    ("No track", "An effort with no file", "23,718 (2,180 of them CRC's)"),
    ("Blank", "Matched, and the file has no points yet", "23"),
    ("Unmatched", "A stored file not yet matched to an effort", "199 (2 of them blank)"),
    ("Lost", "Neither matched nor stored. None are left once blank files are made", "0"),
]

# ---------------------------------------------------------------------------
# Step 3: app
# ---------------------------------------------------------------------------

STEP3 = [
    "The website does not read dbo's tables directly. It reads views: each one picks the columns a page needs "
    "from a dbo table and gives them simple names. The new process keeps today's 10 views, with the same names "
    "and columns, so the website does not need to change.",
    "One thing changes for all of them: today they only show CRC's records. Now every research group's data is "
    "in them, and the views no longer filter to CRC.",
    "CRC is no longer a rule in the data but a filter on the website. Explore, the Efforts and Sightings lists "
    "and the export show CRC's records when they first open, and the Research Group filter can show any other "
    "group, several groups, or every group.",
]

# (view, what the website uses it for, from, what changes).
APP_VIEWS = [
    ("daily_effort", "Efforts: the Efforts list and each effort's page", "DailyEffortT",
     "Every research group. Its id is the hashed Primary Key; DB167's IDs are still in legacy_daily_effort_id."),
    ("daily_event", "The day log on each effort's page", "DailyEventT",
     "Every research group. Uses the hashed Primary Keys."),
    ("daily_condition", "Weather readings on each effort's page", "DailyConditionT",
     "Every research group. Uses the hashed Primary Keys."),
    ("effort_timeline", "The timeline of day-log entries, weather and sightings on an effort's page",
     "DailyEventT, DailyConditionT, SightingT", "Every research group."),
    ("sighting", "Sightings: the Explore map and list, and each sighting's page", "SightingT",
     "Every research group. Its id is the hashed Primary Key. The number of animals identified comes from "
     "IdentificationT."),
    ("sample", "Samples on each sighting's page", "SampleT", "Every research group. Uses the hashed Primary Keys."),
    ("track", "GPS tracks on the map and each effort's page", "TrackT",
     "Every research group. Its effort is the FK daily_effort_id, pointing at DailyEffortT.id."),
    ("species", "The species filter and names", "SpeciesT",
     "Every species any sighting uses, not only those CRC has seen."),
    ("vessel", "The vessel filter and names", "VesselListT",
     "Every vessel any effort or sighting uses, one row per vessel."),
    ("event_code", "Names of the day-log codes", "EventCodeT", "Includes the 51 codes added."),
]

# Read directly by the sighting page, outside the views.
DIRECT_READS = [
    ("Sighting events", "From SightingEventT, by its FK sighting_id, as today."),
    ("Other species present", "From OtherSpeciesT, by its FK sighting_id, as today."),
    ("Tag deployments", "From TagSummaryT, by its new FK sighting_id, instead of matching Research Group, Vessel, "
                        "Date and Sighting each time."),
    ("Individuals identified", "From IdentificationT and IndividualT instead of SightingIdentificationT."),
]


# ---------------------------------------------------------------------------
# Today vs new
# ---------------------------------------------------------------------------

DIFF_HELP = [
    "'Today' is the live website's database, copied on 19 October 2026. 'New' is what the new process produces "
    "from today's copy of DB167. The first part compares how the data is organised; the second compares how "
    "many records each table holds, and explains every difference.",
]

# How the data is organised, by area: (what, today, new).
SCHEMA_DIFF = [
    ("raw: the untouched copy of DB167", [
        ("Tables", "34",
         "40. DB167 has gained 4 tables since the live site last copied it (AnnualDBT, DatabaseFieldT, "
         "DatabaseTableT and SpeciesT), and today's process skipped 2 (DailyEffortT_IanDB_SnapshotT and "
         "SightingT_IanDB_SnapShotT)"),
        ("Columns", "As DB167 had them when it was last copied",
         "18 more, which DB167 has gained since: DailyEffortT (BmSent, ErSent, MnSent, PhotoDataDate), "
         "IdentificationT (Drone Image, MatchPQ?, Priority, SentToMatching, SentToMnID, Tag), SampleT (Latitude, "
         "Longitude), SightingEventT (EventDateTime, Time), TagSummaryT (RecoverDate, RecoverTime, TagOffDate, "
         "TagOffTime). None removed or changed"),
    ]),
    ("dbo: the copy the website is built from", [
        ("Tables", "34 copies of raw's tables, plus VesselListT",
         "16 copies, the tables the website uses and their category tables, plus VesselListT. The other 24 stay in "
         "raw only"),
        ("Views", "7 of DB167's views", "The same 7"),
        ("Primary Keys", "DB167's IDs everywhere",
         "DB167's IDs, except the 8 tables that get a hashed Primary Key: DailyEffortT, DailyEventT, "
         "DailyConditionT, SightingT, SightingEventT, OtherSpeciesT, SampleT and IdentificationT"),
        ("Foreign Keys", "40, all on DB167's ID columns",
         "Foreign Keys into those 8 tables point at the hashed Primary Keys. New: every record to ResearchGroupT, "
         "and to SpeciesT where it records a species. TrackT's effort FK points at the hashed Primary Key"),
        ("Columns", "Every raw column, plus the vessel FK, the species FK and the calculated columns",
         "The same, plus the hashed Primary Key in 8 tables, and the new Foreign Keys. Nothing removed"),
        ("Values", "As in raw, with the old process's fixes",
         f"Spelling made consistent in every dbo column: {MERGED:,} values merged, {TRIMMED:,} trimmed, "
         f"{EMPTIED:,} empty values made NULL"),
        ("Category tables", "VesselListT with one row per spelling; ResearchGroupT as DB167 has it",
         "VesselListT with one row per vessel; ResearchGroupT with 375 missing groups added"),
    ]),
    ("app: what the website reads", [
        ("Views", "10", "The same 10, with the same columns"),
        ("Records shown", "CRC only", "Every research group, with CRC shown by default as a filter that can be changed"),
        ("IDs", "DB167's IDs",
         "The hashed Primary Key for efforts, day-log entries, weather, sightings and samples. DB167's IDs are "
         "still there, and the website's addresses keep using them"),
        ("Audit log", "Every edit made on the website, and some entries the old import wrote itself",
         "Only edits made on the website, re-applied after every rebuild"),
    ]),
]

# Row differences, measured: one entry per table. See the file.
DIFF = _load("pipeline_diff.json")["tables"]
