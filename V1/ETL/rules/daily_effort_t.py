"""DailyEffortT — one vessel effort on one day."""

from . import Rule, Correction, NORMALIZE, MAP

TABLE = "DailyEffortT"

RULES = [
    Rule(
        id="R1", table=TABLE, kind=NORMALIZE,
        description="Trim surrounding whitespace and fold case-only spellings "
                    "into the form used most often on the same column.",
        columns=["Launch", "Locality", "Return", "Region", "Sub-area",
                 "Survey Type", "Project/Objective", "Record Source"],
    ),
    Rule(
        id="R3", table=TABLE, kind=MAP, columns=["Survey Type"],
        description="Survey type wording. Same category, written differently.",
        mapping={
            "Non-Standardized Large Vessel": "Large Vessel Non-Standardized",
            "Land Observation": "Land",
            "ENTANGLEMENT": "Entanglement Response",
            "ENT": "Entanglement Response",
            "Uknown": "Unknown",
        },
    ),
]

# R4 needs two columns at once, so it is expressed directly. Total Distance is
# text with its unit in a second column, which makes the number alone
# meaningless. dbo stores one number, in nautical miles, in a new column.
DISTANCE_SQL = """
    UPDATE dbo."DailyEffortT" SET total_distance_nm = round((
        CASE lower(btrim(coalesce("Distance Units", '')))
            WHEN 'km' THEN btrim("Total Distance")::numeric * 0.539957
            WHEN 'm'  THEN btrim("Total Distance")::numeric * 0.000539957
            ELSE btrim("Total Distance")::numeric
        END)::numeric, 3)
    WHERE "Total Distance" ~ '^\\s*[0-9]+(\\.[0-9]+)?\\s*$'
      AND lower(btrim(coalesce("Distance Units", ''))) IN ('nm','nmi','mn','km','m')
"""

CORRECTIONS = [
    Correction(
        id="LOC-001", table=TABLE, pk="DailyEffortID", expected=5,
        description="Locality spellings that differ by more than case, merged "
                    "into the spelling used on the other records.",
        set='"Locality" = CASE "Locality" '
            "WHEN 'N Cordell Bank' THEN 'N. Cordell Bank' "
            "WHEN 'ZITTEL''S' THEN 'Zittels' "
            "WHEN 'Everett, N Puget Sound' THEN 'Everett/N. Puget Sound' "
            "WHEN 'Pt. St. George' THEN 'Pt St George' "
            "WHEN 'Pt. St.George' THEN 'Pt St George' END",
        where='"Locality" IN (\'N Cordell Bank\', \'ZITTEL\'\'S\', '
              "'Everett, N Puget Sound', 'Pt. St. George', 'Pt. St.George')",
    ),
    Correction(
        id="LOC-002", table=TABLE, pk="DailyEffortID", expected=6,
        description="Sekiu and Seiku are the same town on the Strait of Juan de "
                    "Fuca with two vowels swapped. Sekiu is used on 36 CRC "
                    "records, Seiku on 11. Applied to all three place columns, "
                    "since the misspelling turns up in Launch and Return.",
        set='"Launch" = replace(replace("Launch", \'Seiku\', \'Sekiu\'), \'seiku\', \'Sekiu\'), '
            '"Locality" = replace(replace("Locality", \'Seiku\', \'Sekiu\'), \'seiku\', \'Sekiu\'), '
            '"Return" = replace(replace("Return", \'Seiku\', \'Sekiu\'), \'seiku\', \'Sekiu\')',
        where='"Launch" ILIKE \'%seiku%\' OR "Locality" ILIKE \'%seiku%\' '
              "OR \"Return\" ILIKE '%seiku%'",
    ),
    Correction(
        id="GEO-001", table=TABLE, pk="DailyEffortID", expected=15,
        description="Sub-area spellings merged.",
        set='"Sub-area" = CASE "Sub-area" '
            "WHEN 'SE Alaska' THEN 'Southeast Alaska' "
            "WHEN 'Nothern Washington' THEN 'Northern Washington' "
            "WHEN 'Nothern Oregon' THEN 'Northern Oregon' "
            "WHEN 'Queen Charlottes' THEN 'Queen Charlotte Islands' END",
        where='"Sub-area" IN (\'SE Alaska\', \'Nothern Washington\', '
              "'Nothern Oregon', 'Queen Charlottes')",
    ),
    Correction(
        id="GEO-F01", table=TABLE, pk="DailyEffortID",
        description="Efforts recorded as US West Coast with an Alaskan "
                    "sub-area and Alaskan localities. Region corrected.",
        set='"Region" = \'Alaska\'',
        where='"Region" = \'US West Coast\' AND "Sub-area" IN '
              "('SE Alaska', 'Southeast Alaska', 'Gulf of Alaska')",
    ),
    Correction(
        id="GEO-F02", table=TABLE, pk="DailyEffortID",
        description="One effort had Sub-area Northern Baja California with a "
                    "locality of Monterey Bay. The sub-area is wrong, not the "
                    "region, so it was cleared. This record is why GEO-F01 is "
                    "not a blanket trust-the-locality rule.",
        set='"Sub-area" = NULL',
        where='"Sub-area" = \'Northern Baja California\' '
              "AND \"Locality\" ILIKE '%Monterey%'",
    ),
    Correction(
        id="GEO-F03", table=TABLE, pk="DailyEffortID",
        description="A trip from San Diego into Mexico. Neither region is "
                    "wrong; set to Mexico to agree with its sub-area. Recorded "
                    "apart from GEO-F01 because it is a judgement about a real "
                    "border crossing, not a correction of an error.",
        set='"Region" = \'Mexico\'',
        where='"Locality" ILIKE \'Mission Bay to Ensendada%\'',
    ),
]
