"""DailyEventT — a timestamped, positioned log entry made during an effort."""

from . import Rule, NORMALIZE

TABLE = "DailyEventT"

RULES = [
    Rule(
        id="R1", table=TABLE, kind=NORMALIZE,
        description="Trim surrounding whitespace and fold case-only spellings "
                    "into the form used most often on the same column.",
        columns=["Code", "Line", "ObsL", "ObsR", "Rec"],
    ),
]

# R7. Same zero-pair rule as SightingT: (0,0) means the position was not
# recorded, not that the boat was in the Gulf of Guinea.
ZERO_PAIR_SQL = [
    """UPDATE dbo."DailyEventT" SET "Dec Lat" = NULL, "Dec Long" = NULL
       WHERE "Dec Lat" = 0 AND "Dec Long" = 0""",
]

CORRECTIONS = []
