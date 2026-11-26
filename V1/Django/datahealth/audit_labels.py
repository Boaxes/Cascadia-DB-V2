"""
How the Audit Log pages name what a change touched. The log itself keeps the
raw names (track_status, daily_effort_id) and the website's internal ids;
these only choose what the pages show.

A change to a field is shown under a plain Title Case name, and a field that
holds an Effort is shown as the Effort's number (its Legacy ID), not the long
internal number the website keeps.
"""

import re

# Names that Title Case alone does not make plain.
FIELD_LABELS = {
    "daily_effort_id": "Effort",
    "EffortID": "Effort",
    "depth_m": "Depth (m)",
    "length_nm": "Length (nm)",
    "geom": "Track Line",
    "version": "Earlier Version Kept",
    "TrackFileName": "Track File Name",
}

# The fields that hold an Effort's internal id, shown as its number.
EFFORT_FIELDS = ("daily_effort_id",)


def field_label(name):
    """track_status -> Track Status, StartTime -> Start Time, TrackID -> Track ID."""
    if name in FIELD_LABELS:
        return FIELD_LABELS[name]
    words = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(name).replace("_", " ")).split()
    return " ".join("ID" if w.lower() == "id" else w[:1].upper() + w[1:] for w in words) or str(name)


def effort_ids(changes_list):
    """The internal Effort ids named by the Effort fields of these entries'
    changes, for effort_numbers."""
    found = set()
    for changes in changes_list:
        for name in EFFORT_FIELDS:
            for side in ("old", "new"):
                value = ((changes or {}).get(name) or {}).get(side)
                if value is not None:
                    found.add(int(value))
    return found


def effort_numbers(cursor, ids):
    """{internal id: Effort number} for these ids, in one query."""
    if not ids:
        return {}
    cursor.execute('SELECT id, "DailyEffortID" FROM dbo."DailyEffortT" WHERE id = ANY(%s)', [sorted(ids)])
    return dict(cursor.fetchall())


def shown_changes(changes, numbers):
    """[(label, old, new, name)] for an entry's changes, ready to show. An
    Effort id becomes the Effort's number (or "Effort Removed" if it has gone),
    and is left out when the entry already says the number in EffortID."""
    out = []
    for name, change in (changes or {}).items():
        old, new = change.get("old"), change.get("new")
        if name in EFFORT_FIELDS:
            if "EffortID" in changes:
                continue
            old, new = (None if v is None else numbers.get(int(v), "Effort Removed") for v in (old, new))
        out.append((field_label(name), old, new, name))
    return out
