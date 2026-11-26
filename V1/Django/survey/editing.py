"""
Which fields can be edited, and what happens after they are.

The application writes through the `app` views, but the audit log records the
`dbo` table and column underneath, so a field is described once here by its real
column name and everything else follows from that.

Only fields worth correcting are listed. Identifiers, the links between records,
and anything the import derives are left out: a sighting's key is not a typo to
be fixed, and a derived value is recomputed rather than typed.
"""

import datetime

from django.db import connection


class Field:
    def __init__(self, column, label, kind="text", note=None, choices=None):
        self.column = column          # the dbo column, which is what is logged
        self.label = label
        self.kind = kind              # text | textarea | number | integer | date | time | species
        self.note = note
        self.choices = choices

    @property
    def name(self):
        """A form field name. Column names contain spaces and punctuation."""
        return "f_" + self.column.replace(" ", "_").replace("?", "")


POSITION_TYPES = ["Precise", "Calculated", "Estimated", "General"]
SIGHT_TYPES = ["S", "SBE", "SE", "UNK"]

SIGHTING_FIELDS = [
    Field("species_id", "Species", kind="species",
          note="The species this sighting is filed under. The original text is "
               "kept either way and shown as recorded."),
    Field("Sighting", "Sighting Number"),
    Field("Date", "Date", kind="date"),
    Field("Start Time", "Time", kind="time"),
    Field("Start Dec Lat", "Latitude", kind="number",
          note="Decimal degrees. Editing either coordinate redraws the point "
               "on the map."),
    Field("Start Dec Long", "Longitude", kind="number"),
    Field("End Dec Lat", "End Latitude", kind="number"),
    Field("End Dec Long", "End Longitude", kind="number"),
    Field("Position Type", "Position Type", choices=POSITION_TYPES),
    Field("Sight Type", "Sighting Type", choices=SIGHT_TYPES),
    Field("Est Size Best", "Best Size Estimate", kind="integer"),
    Field("Est Size Min", "Smallest Estimate", kind="integer"),
    Field("Est Size Max", "Largest Estimate", kind="integer"),
    Field("num_calves", "Calves", kind="integer"),
    Field("Group Beh", "Group Behaviour"),
    Field("Group Type", "Group Type"),
    Field("depth_m", "Depth (m)", kind="number"),
    Field("Comments", "Comments", kind="textarea"),
]

EFFORT_FIELDS = [
    Field("Date", "Date", kind="date"),
    Field("Start Time", "Start Time", kind="time"),
    Field("End Time", "End Time", kind="time"),
    Field("Launch", "Launch"),
    Field("Locality", "Locality"),
    Field("Return", "Return"),
    Field("Region", "Region"),
    Field("Sub-area", "Sub-Area"),
    Field("Survey Type", "Survey Type"),
    Field("Project/Objective", "Project or Objective"),
    Field("Personnel", "Personnel"),
    Field("total_distance_nm", "Distance (nm)", kind="number"),
    Field("Survey Comments", "Comments", kind="textarea"),
]

FIELDS = {"sighting": SIGHTING_FIELDS, "daily_effort": EFFORT_FIELDS}

# Editing a coordinate redraws the point the map reads. That is a trigger in
# `dbo` rather than something done here, so it also covers a correction made in
# DBeaver or by the Access front ends -- see ETL/schema/dbo_geometry.sql.


def current(table, key_column, pk, fields):
    """The values now, keyed by column."""
    columns = ", ".join('"' + f.column.replace('"', '""') + '"' for f in fields)
    with connection.cursor() as cur:
        cur.execute(f'SELECT {columns} FROM dbo."{table}" WHERE "{key_column}" = %s',
                    [pk])
        row = cur.fetchone()
    if row is None:
        return None
    return {f.column: value for f, value in zip(fields, row)}


def display(field, value):
    """
    One value as an HTML form control wants it.

    A date input needs `YYYY-MM-DD` and a time input `HH:MM`. Django would
    otherwise render a date as `Aug. 22, 2005, midnight`, which the browser
    shows as empty and the database rejects on the way back in.
    """
    if value is None:
        return ""
    if field.kind == "date":
        return value.strftime("%Y-%m-%d")
    if field.kind == "time":
        # Keep the seconds where there are any: dropping them would make an
        # untouched time read as a change and cut it on save.
        return value.strftime("%H:%M:%S" if value.second else "%H:%M")
    return value


def parse(field, raw):
    """One submitted value, as the column's type, or None for empty."""
    if not isinstance(raw, str):
        raw = "" if raw is None else str(raw)
    raw = raw.strip()
    if raw == "":
        return None
    if field.kind == "number":
        return float(raw)
    if field.kind in ("integer", "species"):
        return int(raw)
    if field.kind == "date":
        return datetime.date.fromisoformat(raw)
    if field.kind == "time":
        # A browser sends HH:MM, but a value round-tripped through a hidden
        # field on the confirmation step comes back with seconds.
        return datetime.time.fromisoformat(raw if len(raw) > 5 else raw + ":00")
    return raw


def changed(before, submitted):
    """
    Only the fields whose value actually moved.

    Compared as text, because a form always submits text and the column may
    hold a number: 33.15 read back from the database is not "33.15" in Python,
    and treating that as a change would log an edit that never happened.
    """
    out = {}
    for column, value in submitted.items():
        old = before.get(column)
        if _same(old, value):
            continue
        out[column] = value
    return out


def _same(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, datetime.datetime) and isinstance(b, datetime.date):
        return a.date() == b
    if isinstance(a, datetime.date) and isinstance(b, datetime.datetime):
        return a == b.date()
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def deletion_warning(table, key_column, pk):
    """
    What else would go, in one sentence per table.

    Counted rather than listed: the point is to say plainly that a delete
    reaches further than the record on screen, not to print two hundred rows.
    """
    from datahealth.audit import collect

    rows, _ = collect(table, key_column, pk)
    # Singular and plural given, because appending an s produces "log entrys".
    LABELS = {
        "SightingT": ("sighting", "sightings"),
        "SampleT": ("sample", "samples"),
        "SightingIdentificationT": ("photo identification", "photo identifications"),
        "IdentificationT": ("identification record", "identification records"),
        "SightingEventT": ("sighting event", "sighting events"),
        "OtherSpeciesT": ("other species record", "other species records"),
        "SampleIdentificationT": ("sample identification", "sample identifications"),
        "DailyConditionT": ("weather reading", "weather readings"),
        "DailyEventT": ("log entry", "log entries"),
        "TagSummaryT": ("tag deployment", "tag deployments"),
        "EffortCrewT": ("crew record", "crew records"),
        "TrackingT": ("tracking record", "tracking records"),
        "PermitTakeT": ("permit record", "permit records"),
        "AdditionalCameraT": ("camera record", "camera records"),
        "SightingFollowT": ("follow record", "follow records"),
        "DroneDeploymentT": ("drone deployment", "drone deployments"),
        "DroneTargetAnimalT": ("drone target", "drone targets"),
        "TrackT": ("GPS track", "GPS tracks"),
    }
    lines = []
    for name, records in sorted(rows.items(), key=lambda kv: -len(kv[1])):
        count = len(records)
        singular, plural = LABELS.get(name, (name, name))
        lines.append(f"{count} {singular if count == 1 else plural}")
    return lines
