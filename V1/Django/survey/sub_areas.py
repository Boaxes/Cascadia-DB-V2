"""
Sub-areas, as Doug Sandilands corrected them (October 2026).

sub_areas.csv has one row per Sub-area spelling found in DailyEffortT: its ID,
which runs north to south, the spelling, the corrected sub-area it belongs to,
and Doug's count of efforts for it. Sub-area is typed by hand, so one place is
often spelled several ways ('So California' and 'Southern California').

The filter offers each corrected sub-area once, in ID order, those with 250 or
more efforts first and then the rest. Choosing one matches every spelling
listed under it, ignoring capitals and spaces at either end.
"""

import csv
from pathlib import Path

MAIN_THRESHOLD = 250


def normalise(text):
    return " ".join((text or "").split()).lower()


def _load():
    """[{name, spellings, main}] in north-to-south order."""
    groups = {}
    with open(Path(__file__).with_name("sub_areas.csv"), newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row["Corrected Sub-Area"].strip()
            group = groups.setdefault(name, {"name": name, "order": int(row["ID"]), "spellings": set(),
                                             "count": 0})
            group["order"] = min(group["order"], int(row["ID"]))
            group["spellings"].add(normalise(row["Sub-Area Database Entries"]))
            group["count"] = max(group["count"], int(row["Count"]))
    ordered = sorted(groups.values(), key=lambda g: g["order"])
    return [{"name": g["name"], "spellings": g["spellings"], "main": g["count"] >= MAIN_THRESHOLD}
            for g in ordered]


GROUPS = _load()


def choices(values):
    """(main, other): the corrected names with at least one effort among the
    given Sub-area values, each list north to south."""
    present = {normalise(v) for v in values if v}
    shown = [g for g in GROUPS if g["spellings"] & present]
    return [g["name"] for g in shown if g["main"]], [g["name"] for g in shown if not g["main"]]


def matching_values(name, values):
    """The Sub-area values, exactly as stored, that belong to a corrected name."""
    group = next((g for g in GROUPS if g["name"] == name), None)
    if group is None:
        return []
    return sorted(v for v in values if v and normalise(v) in group["spellings"])
