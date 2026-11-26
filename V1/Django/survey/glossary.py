"""Plain English for anything on screen a reader would have to guess at.

Two things live here. TERMS is one entry per word on the site, written once and
used by every page through the `{% tip %}` tag.

The rest is what the bare codes in the data mean. DB167 stores two sets of
codes with no lookup table anywhere in the database, so none of it was written
down. Each reading below was worked out from the data itself and carries the
evidence that produced it: sampled comments on the rows using the code, the
average hour of the day it appears, and which columns it fills.

None of that is written into the database. A meaning is a reading of the data,
not a fact about it, so correcting one should not need a rebuild. It is read at
display time.

Codes the evidence did not settle are listed in assumptions.NEEDS_REVIEW, keyed
`event:CODE` and `sight_type:VALUE`, and show a review flag wherever they
appear.

    code: (reading, what the evidence was)
"""

# daily_event.code, 64 values across 27,000 rows.
EVENT_CODES = {
    "B": ("Begin effort",
          "Earliest average hour at 8.8, and it is already what the rebuild "
          "reads an effort's start position from"),
    "T": ("End effort",
          "Latest average hour at 16.3, and it is already the end position "
          "source"),
    "R": ("Resume effort",
          "A comment on one row reads: Used to be a B for the second effort "
          "of the day, changed to an R"),
    "E": ("End of day",
          "Average hour 16.1, alongside T. Comments read END OF DAY and END "
          "EFFORT FOR RETRIVAL"),
    "O": ("Off effort",
          "Comments are breaks, meals, darkness, crew changes and refuelling"),
    "OE": ("Off effort",
           "Comments are stops to listen and to put the array in the water"),
    "RE": ("Resume effort",
           "Comments are returning to course and to speed after a stop"),
    "BO": ("Begin on effort",
           "Comments read BLT ON EFFORT and ABD ON EFFORT"),
    "XO": ("Break off from the current activity",
           "Comments read BREAK TO CHASE WHALE and CHANGE COURSE TO CHASE "
           "ORCAS"),
    "P": ("Position or course note",
          "The most common code by far. Comments are headings, speeds and "
          "search notes, and only 22 percent carry any comment at all"),
    "C": ("Comment",
          "96 percent carry comment text and the text is miscellaneous "
          "remarks about the day"),
    "OBS": ("Observer change",
            "The only code in the table that fills the observer and recorder "
            "columns, on 1,055 of its 1,461 rows"),
    "W": ("Weather change",
          "Every comment is a weather change: BEAUFORT INCREASE, In fog bank, "
          "Increasing swell"),
    "V": ("Vessel sighting",
          "Every one of its 30 comments reads (Fishing vessel code, Wincruz)"),
    "BT": ("Begin transect",
           "Comments read Begin transect in separation zone of shipping lanes "
           "and 50 meter line, southbound"),
    "ET": ("End transect",
           "Comments read ending transect heading towards Santa Rosa Channel "
           "and end 200 m line"),
    "RT": ("Resume transect",
           "A comment reads: whale not resighted, resuming survey"),
    "XT": ("Leave the transect",
           "Comments are diversions: STOP FOR RHIB LAUNCH, DIVERT FOR BEAKED "
           "WHALE AND SLOW SPEED"),
    "ST": ("Start transect",
           "Comments are headings and shipping lane positions, which fits a "
           "transect start but does not settle it against shipping transit"),
    "SBT": ("Begin transect",
            "Comments read MID TRANSECT ABD ON and BLT ON EFFORT"),
    "SET": ("End transect", "Reads as the counterpart to SBT"),
    "H": ("Hydrophone listening station",
          "Comments read no song, NOTHING HEARD and TEMP 31.2, and 98 percent "
          "of rows carry one"),
    "Rec-H": ("Hydrophone recording",
              "Comments are all of the form B2 R1, a Beaufort and a recording "
              "number"),
    "EchoLog-Beg": ("Start echosounder logging",
                    "Average hour 11.1 against 16.3 for the end code, so the "
                    "pair brackets the day the right way round"),
    "EchoLog-End": ("Stop echosounder logging", "The counterpart to the above"),
    "PB-Beg": ("Start playback experiment",
               "Comments describe sound transmission and distance from the "
               "animal"),
    "PB-End": ("End playback experiment", "The counterpart to the above"),
    "PB-Ends": ("End playback experiment", "Spelling variant of PB-End"),
    "Dep-SS": ("Deploy sound source",
               "Comments read Sound source in water and redploy sound source"),
    "Rec-SS": ("Recover sound source",
               "Comments read sound source up"),
    "Drone_L": ("Drone launch",
                "Comments are flight numbers such as f4 and f15"),
    "Drone_R": ("Drone recovery",
                "Comments name the aircraft and the sighting it flew over"),
    "UAS-Up": ("Drone launch", "Every comment reads UAS UP"),
    "UAS-Down": ("Drone recovery", "The counterpart to UAS-Up"),
    "Dep-UAS": ("Drone launch",
                "Comments read f6 s and flight 1, a flight number and a start"),
    "Rec-UAS": ("Drone recovery",
                "Comments read f6 e and f2 end, the same flight numbers ending"),
    "TagRec": ("Tag recovery",
               "Comments describe recovering a numbered tag and what was found "
               "on the darts"),
    "Tag-Rec": ("Tag recovery", "Spelling variant of TagRec"),
    "Sample": ("Sample taken",
               "Comments are sample identifiers such as CRC-20191101-MUS-71"),
    "SB": (None, "28 rows and not one comment between them"),
    "SE": (None, "28 rows and not one comment between them"),
    "S": (None, "37 rows and not one comment between them"),
    "OS": (None, "2 rows"),
    "OB": (None, "1 row"),
    "RO": (None, "4 rows"),
    "EO": (None, "4 rows"),
    "SP": (None, "2 rows"),
    "SH": (None, "1 row"),
    "CPA": ("Closest point of approach",
            "2 rows. The abbreviation is standard in survey work"),
    "P/U": ("Pick up", "Reads as pick up, matching the p/u spelling"),
    "p/u": ("Pick up", "Reads as pick up"),
    "0": (None, "2 rows holding a zero rather than a code"),
}

# Codes that are another code with different capitalisation, or two codes
# recorded at once. Kept apart so the list above stays one entry per meaning.
EVENT_CODE_VARIANTS = {
    "p": "P", "c": "C", "w": "W", "t": "T", "C.": "C",
    "SB/SE": "SB and SE together", "SE/SB": "SB and SE together",
    "ET/OE": "ET and OE together", "ET/ST": "ET and ST together",
    "C/H": "C and H together", "W/C": "W and C together",
}

# sighting.sight_type, four values across 29,405 rows. What the letters stand
# for was not recovered. What each value marks is clear from the data, and that
# is what somebody reading a record needs.
SIGHT_TYPES = {
    "S": ("Seen in passing, not approached",
          "11 percent photographed, 4 percent carry an end position, and the "
          "mean group size is 27, which is the large dolphin schools counted "
          "at a distance"),
    "SBE": ("Approached and photographed, no end position taken",
            "94 percent photographed but only 10 percent carry an end "
            "position. Mean group size 7.3"),
    "SE": ("Approached and photographed, and where the boat left the group "
           "was recorded",
           "90 percent photographed and 96 percent carry an end position, "
           "which is the only value where that column is reliably filled"),
    "UNK": (None,
            "Used between 2004 and 2009 and never since. Its photograph rate, "
            "end position rate and group size all match S"),
}

def event_code(code):
    """(reading, evidence) for an event code, following variants."""
    if code in EVENT_CODES:
        return EVENT_CODES[code]
    target = EVENT_CODE_VARIANTS.get(code)
    if target and target in EVENT_CODES:
        return EVENT_CODES[target]
    return (None, "")


# One sentence per term, and only for terms an outsider could not read off the
# field name: codes, notation and survey jargon. A plain field such as
# "Research group" or "Calves" carries no tip.
TERMS = {
    # Sighting
    "group_type": "Freehand notation: Single, Pair and Trio are counts, Agg is "
                  "a loose aggregation, and 1+1 is one adult with one calf.",
    "identified": "Animals matched to Cascadia's photo-identification catalogue.",
    "position": "Where the vessel was, not the animal; the two are usually "
                "within a few metres.",
    "end_position": "Where the vessel was when it left the group.",
    "species_uncertain": "The observer marked the species with a question mark.",
    "species_raw": "Two species were written in one field, so the text is shown "
                   "as recorded.",

    # Explore
    "clusters": "Nearby sightings are drawn as one numbered circle; turn this "
                "off to see every sighting as its own dot.",
    "track_gap": "Dashed where the GPS recorded nothing for over 30 minutes.",
    "excluded_no_position": "They match the filters but have no coordinates; "
                            "they are still in the list and in an export.",

    # Export
    "export_areas": "Each page keeps its own filters, so filtering Sightings "
                    "does not change an export from Explore.",
    "export_csv": "One row per record; opens directly in Excel or R.",
    "export_excel": "An .xlsx workbook with the header row frozen.",
    "export_geojson": "For QGIS and other mapping software; records without a "
                      "position are left out.",
    "export_tracks": "Adds the full-resolution GPS points for every effort in "
                     "the export, not the simplified lines the map draws.",
}


def _coded(prefix, source):
    """One tip per code: what it means, or that nobody recorded it. The
    evidence behind each reading stays above, for anyone checking it."""
    for code, (reading, _evidence) in source.items():
        TERMS[f"{prefix}:{code}"] = f"{code}: {reading or 'meaning not recorded'}."


_coded("event", EVENT_CODES)
_coded("sight_type", SIGHT_TYPES)


def text(key):
    """The explanation for a term, or an empty string if there is none."""
    return TERMS.get(key, "")
