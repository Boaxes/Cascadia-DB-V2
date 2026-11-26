"""DailyConditionT — a sea-state and weather reading taken during an effort."""

from . import Rule, Correction, NORMALIZE

TABLE = "DailyConditionT"

RULES = [
    Rule(
        id="R1", table=TABLE, kind=NORMALIZE,
        description="Trim surrounding whitespace and fold case-only spellings "
                    "into the form used most often on the same column. "
                    "Precipitation codes are folded but never merged beyond "
                    "that -- DB167 documents nowhere what they mean.",
        columns=["Quality", "Precipitation", "Visibility"],
    ),
]

CORRECTIONS = [
    Correction(
        id="CND-001", table=TABLE, pk="DailyConditionID",
        description="The Beaufort scale runs 0 to 12. These were outside it. "
                    "Some look like transposed digits but none can be "
                    "recovered reliably, so all were cleared.",
        set='"Beaufort" = NULL',
        where='"Beaufort" IS NOT NULL AND ("Beaufort" < 0 OR "Beaufort" > 12)',
    ),
    Correction(
        id="CND-003", table=TABLE, pk="DailyConditionID",
        description="Valid observation quality codes are E, G, VG, F and P. "
                    "These held something else and were cleared.",
        set='"Quality" = NULL',
        where="""btrim(upper("Quality")) NOT IN ('E','G','VG','F','P')
                 AND "Quality" IS NOT NULL AND btrim("Quality") <> ''""",
    ),
]

# CND-002 -- V1 cleared 20 swell readings for being outside 0-20 feet. That
# range is invented; it is not a defined scale, and 23 and 30 foot swells are
# entirely possible offshore. Dropped, not ported.
