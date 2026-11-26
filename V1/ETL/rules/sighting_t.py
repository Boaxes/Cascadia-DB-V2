"""SightingT — one observation of marine mammals."""

from . import Rule, Correction, NORMALIZE, MAP

TABLE = "SightingT"

RULES = [
    Rule(
        id="R1", table=TABLE, kind=NORMALIZE,
        description="Trim surrounding whitespace and fold case-only spellings "
                    "into the form used most often on the same column.",
        columns=["Species", "Group Beh", "Group Type", "Position Type",
                 "Sight Type", "Other Beh 1", "Other Beh 2", "Other Beh 3",
                 "Acoustics", "DOT", "PreyType", "RangeSource"],
    ),
    Rule(
        id="R2", table=TABLE, kind=MAP, columns=["Species"],
        description="Species synonyms: different strings for the same animal.",
        mapping={
            "Zica": "Zc",              # both are Ziphius cavirostris
            "UD": "UnDelph",           # unidentified delphinid
            "Ud": "UnDelph",
            "UC": "UnCet",             # unidentified cetacean
            "Turtle": "TURT-UN",
            "UnTurt": "TURT-UN",
            "LST": "TURT-LB",          # leatherback sea turtle
            "Leatherback": "TURT-LB",
            "Olive Ridley Turtle": "TURT-OR",
            "Dc.": "Dc",
            "bm.": "Bm",
        },
    ),
]

# R6. Num Calves is free text with 95 distinct values, many not numbers: unk,
# nd, 1?, 0?, un. A clean number is kept, everything else is left empty. `1?` is
# an observer who thinks they saw one calf; reading it as a confirmed 1 would
# add 163 unconfirmed calves to the dataset.
CALVES_SQL = """
    UPDATE dbo."SightingT" SET num_calves = btrim("Num Calves")::integer
    WHERE "Num Calves" ~ '^\\s*[0-9]+\\s*$'
"""

# R5. Depth is a number with its unit in a second column.
DEPTH_SQL = """
    UPDATE dbo."SightingT" SET depth_m = round((
        CASE lower(btrim(coalesce("D units", '')))
            WHEN 'ft'  THEN "Depth" * 0.3048
            WHEN 'feet' THEN "Depth" * 0.3048
            WHEN 'fm'  THEN "Depth" * 1.8288
            WHEN 'fathoms' THEN "Depth" * 1.8288
            ELSE "Depth"
        END)::numeric, 2)
    WHERE "Depth" IS NOT NULL
      AND lower(btrim(coalesce("D units", ''))) IN ('m','meters','metres','ft','feet','fm','fathoms')
"""

# R7. (0,0) is a real point in the Gulf of Guinea and never where Cascadia
# works, so it means the position was not recorded. Applied to both ends.
ZERO_PAIR_SQL = [
    """UPDATE dbo."SightingT" SET "Start Dec Lat" = NULL, "Start Dec Long" = NULL
       WHERE "Start Dec Lat" = 0 AND "Start Dec Long" = 0""",
    """UPDATE dbo."SightingT" SET "End Dec Lat" = NULL, "End Dec Long" = NULL
       WHERE "End Dec Lat" = 0 AND "End Dec Long" = 0""",
]

CORRECTIONS = [
    Correction(
        id="CRD-002", table=TABLE, pk="SightingID",
        description="Longitude only goes to plus or minus 180. These end "
                    "positions were outside it and could not be recovered, so "
                    "they were cleared.",
        set='"End Dec Lat" = NULL, "End Dec Long" = NULL',
        where='"End Dec Long" < -180 OR "End Dec Long" > 180',
    ),
    Correction(
        id="CRD-003", table=TABLE, pk="SightingID",
        description="A latitude with no longitude, or the reverse, cannot "
                    "describe a location. Both values cleared.",
        set='"Start Dec Lat" = NULL, "Start Dec Long" = NULL',
        where='("Start Dec Lat" IS NULL) <> ("Start Dec Long" IS NULL)',
    ),
    Correction(
        id="CRD-F01", table=TABLE, pk="SightingID", expected=1,
        description="Recorded latitude 47.045 and longitude 124.8272. Positive "
                    "124.8272 is in eastern China; the latitude is on the "
                    "Washington coast where the vessel was working. The "
                    "negative sign had been dropped.",
        set='"Start Dec Long" = -124.8272',
        where='"SightingID" = 114646 AND "Start Dec Long" = 124.8272',
    ),
]
