"""SampleT — a biopsy or tissue sample collected at a sighting."""

from . import Rule, Correction, NORMALIZE

TABLE = "SampleT"

RULES = [
    Rule(
        id="R1", table=TABLE, kind=NORMALIZE,
        description="Trim surrounding whitespace and fold case-only spellings "
                    "into the form used most often on the same column.",
        columns=["Sample Type", "Preservation", "Certainty of Sample ID",
                 "Event", "Reaction", "Sampled by"],
    ),
]

CORRECTIONS = [
    Correction(
        id="SAM-001", table=TABLE, pk="SampleID",
        description="Sample type variants merged. The eleven one-off field "
                    "notes like 'mud? From antenna area' are kept as written "
                    "rather than forced into a category.",
        set='"Sample Type" = CASE btrim("Sample Type") '
            "WHEN 'Skin' THEN 'Skin Only Biopsy' "
            "WHEN 'Skin Only' THEN 'Skin Only Biopsy' "
            "WHEN 'Sample-Other' THEN 'Other' "
            "WHEN 'Blubber only' THEN 'Blubber' END",
        where="""btrim("Sample Type") IN
                 ('Skin', 'Skin Only', 'Sample-Other', 'Blubber only')""",
    ),
    Correction(
        id="SAM-003", table=TABLE, pk="SampleID",
        description="Certainty should be Positive, Probable, Possible, Unknown "
                    "or Negative. These held numbers and were cleared.",
        set='"Certainty of Sample ID" = NULL',
        where='"Certainty of Sample ID" ~ \'^[0-9]+$\'',
    ),
]
