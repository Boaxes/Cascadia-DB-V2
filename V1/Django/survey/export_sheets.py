"""The Export Tool's sheets: what each holds, and the query that fills it.

Two rules decide the shape of an export.

Related values with one row per parent are columns of the parent's sheet. An
Effort has at most one Vessel and (but for 31 old exceptions, where the first
by Track ID is used) one track file, so those are columns on Efforts. A
Sighting has one Species, one Vessel and one Effort, so those are columns on
Sightings. Only records that come many to a parent get a sheet of their own,
and each carries its parent's ID.

Stacked queries combine like an OR. There is one Efforts sheet and one
Sightings sheet however many queries are stacked, a row that matches two
queries appears once, and a Matched Queries column says which queries each row
matched. That column exists only when two or more are stacked.

A query of Efforts can also bring in the Sightings of those Efforts, and a
query of Sightings the Efforts of those Sightings. Those rows join the same two
sheets, and Matched Queries counts the query that brought them in.

Every sheet is written from SQL that reads the current database. The filters
come from filters.py, so an export matches the list it was added from, and the
rows are fetched through a server-side cursor in batches.
"""

import csv
import datetime
import io
import posixpath

from django.core.exceptions import EmptyResultSet
from django.db import connection

from . import export_stack, track_objects
from .exporters import UTC, OutSheet, Zone, file_name
from .models import IMPLAUSIBLE_SPEED_KN, DailyEffort, EffortTimeline, Track

PREVIEW_ROWS = 8
BATCH = 2000


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------


class Column:
    """One column of a sheet. `sql` is what the query selects for it. `fix`
    turns the selected value into the one written, where that takes more than
    SQL. A required column cannot be unticked: it is the ID that ties the
    sheet to its parent."""

    def __init__(self, key, label, kind, sql, group="", appended=False, default=True,
                 required=False, fix=None):
        self.key, self.label, self.kind, self.sql = key, label, kind, sql
        self.group, self.appended, self.default = group, appended, default or required
        self.required, self.fix = required, fix


def _hours(sql):
    return f"round(extract(epoch FROM {sql}) / 3600, 3)"


def _source(table):
    def fix(code):
        if code is None:
            return None
        name, detail = table.get(code, (code, ""))
        return f"{name} ({detail})" if detail else name
    return fix


# The speed a track's recorded length and times imply, which is how the site
# decides a length is corrupted (models.Track.length_is_plausible).
_SUSPECT = f"""CASE WHEN t.length_nm IS NULL OR t.start_time_utc IS NULL OR t.end_time_utc IS NULL
         OR t.end_time_utc <= t.start_time_utc THEN NULL
       ELSE t.length_nm / (extract(epoch FROM t.end_time_utc - t.start_time_utc) / 3600)
            > {int(IMPLAUSIBLE_SPEED_KN)} END"""

# The track an Effort carries: its first by Track ID. An Effort has one, bar 31
# that have two or three, and nothing may add another.
FIRST_TRACK = """LEFT JOIN LATERAL (
    SELECT x.object_key, x.point_count, x.length_nm, x.start_time_utc, x.end_time_utc, x.geom
    FROM app.track x WHERE x.daily_effort_id = {effort}.id ORDER BY x.legacy_track_id LIMIT 1
  ) t ON true"""

EFFORT_COLUMNS = [
    Column("effort_id", "Effort ID", "int", "e.legacy_daily_effort_id", "Effort", required=True),
    Column("date", "Date", "date", "e.effort_date", "Effort"),
    Column("start_time", "Start Time", "time", "e.start_time", "Effort", default=False),
    Column("end_time", "End Time", "time", "e.end_time", "Effort", default=False),
    Column("locality", "Locality", "text", "e.locality", "Effort"),
    Column("region", "Region", "text", "e.region", "Effort"),
    Column("sub_area", "Sub-Area", "text", "e.sub_area", "Effort", default=False),
    Column("survey_type", "Survey Type", "text", "e.survey_type", "Effort"),
    Column("research_group", "Research Group", "text", "e.research_group", "Effort"),
    Column("distance_nm", "Distance (nm)", "float", "e.distance_recorded_nm", "Effort", default=False),
    Column("project_objective", "Project/Objective", "text", "e.project_objective", "Effort", default=False),
    Column("crew", "Crew", "text", "e.personnel", "Effort", default=False),
    Column("launch", "Launch", "text", "e.launch", "Effort", default=False),
    Column("return_location", "Return Location", "text", "e.return_location", "Effort", default=False),
    Column("time_searching", "Time Searching (Hours)", "float", _hours("e.total_survey_effort"), "Effort", default=False),
    Column("time_off_effort", "Time Off Effort (Hours)", "float", _hours("e.time_off_effort"), "Effort", default=False),
    Column("start_latitude", "Start Latitude", "float", "e.start_lat", "Effort", default=False),
    Column("start_longitude", "Start Longitude", "float", "e.start_lon", "Effort", default=False),
    Column("start_source", "Start Position Source", "text", "e.start_coord_source", "Effort", default=False,
           fix=_source(DailyEffort.START_SOURCES)),
    Column("end_latitude", "End Latitude", "float", "e.end_lat", "Effort", default=False),
    Column("end_longitude", "End Longitude", "float", "e.end_lon", "Effort", default=False),
    Column("end_source", "End Position Source", "text", "e.end_coord_source", "Effort", default=False,
           fix=_source(DailyEffort.END_SOURCES)),
    Column("comments", "Comments", "text", "e.survey_comments", "Effort", default=False),
    # The site shows the code where no real name is recorded, so Unknown is not data.
    Column("vessel_code", "Vessel Code", "text", "v.code", "Vessel", True),
    Column("vessel_name", "Vessel Name", "text", "nullif(v.name, 'Unknown')", "Vessel", True),
    Column("track_file", "Track File", "text", "regexp_replace(t.object_key, '^.*/', '')", "Track File", True),
    Column("track_points", "Track Points", "int", "t.point_count", "Track File", True),
    Column("track_length_nm", "Track Length (nm)", "float", "t.length_nm", "Track File", True),
    Column("track_start", "Track Start", "datetime", "t.start_time_utc", "Track File", True, default=False),
    Column("track_end", "Track End", "datetime", "t.end_time_utc", "Track File", True, default=False),
    Column("track_suspect", "Track Length Suspect", "bool", _SUSPECT, "Track File", True, default=False),
]

SIGHTING_COLUMNS = [
    Column("sighting_id", "Sighting ID", "int", "s.legacy_sighting_id", "Sighting", required=True),
    Column("effort_id", "Effort ID", "int", "e.legacy_daily_effort_id", "Sighting"),
    Column("date", "Date", "date", "s.sighting_date", "Sighting"),
    Column("time", "Time", "time", "s.sighting_time", "Sighting"),
    Column("latitude", "Latitude", "float", "s.lat", "Sighting"),
    Column("longitude", "Longitude", "float", "s.lon", "Sighting"),
    Column("group_size_best", "Group Size Best", "int", "s.est_size_best", "Sighting"),
    Column("group_behavior", "Group Behavior", "text", "s.group_behavior", "Sighting", default=False),
    Column("group_size_min", "Group Size Min", "int", "s.est_size_min", "Sighting", default=False),
    Column("group_size_max", "Group Size Max", "int", "s.est_size_max", "Sighting", default=False),
    Column("calves", "Calves", "int", "s.num_calves", "Sighting", default=False),
    Column("group_type", "Group Type", "text", "s.group_type", "Sighting", default=False),
    Column("sighting_type", "Sighting Type", "text", "s.sight_type", "Sighting", default=False),
    Column("photos_taken", "Photos Taken", "bool", "s.photos_taken", "Sighting", default=False),
    Column("individuals_identified", "Individuals Identified", "int", "s.identified_individual_count", "Sighting", default=False),
    Column("depth_m", "Depth (m)", "float", "s.depth_m", "Sighting", default=False),
    Column("number_on_the_day", "Number On The Day", "text", "s.sighting_number", "Sighting", default=False),
    Column("position_type", "Position Type", "text", "s.position_type", "Sighting", default=False),
    Column("end_latitude", "End Latitude", "float", "s.end_lat", "Sighting", default=False),
    Column("end_longitude", "End Longitude", "float", "s.end_lon", "Sighting", default=False),
    Column("species_uncertain", "Species Uncertain", "bool", "s.species_uncertain", "Sighting", default=False),
    Column("species_as_recorded", "Species As Recorded", "text", "s.species_raw", "Sighting", default=False),
    Column("research_group", "Research Group", "text", "s.research_group", "Sighting", default=False),
    Column("comments", "Comments", "text", "s.comments", "Sighting", default=False),
    Column("species_code", "Species Code", "text", "sp.code", "Species", True),
    Column("common_name", "Common Name", "text", "sp.common_name", "Species", True),
    Column("scientific_name", "Scientific Name", "text", "sp.scientific_name", "Species", True),
    Column("vessel_code", "Vessel Code", "text", "v.code", "Vessel", True),
    Column("vessel_name", "Vessel Name", "text", "nullif(v.name, 'Unknown')", "Vessel", True, default=False),
    Column("effort_date", "Effort Date", "date", "e.effort_date", "Effort", True),
    Column("effort_locality", "Effort Locality", "text", "e.locality", "Effort", True),
    Column("effort_region", "Effort Region", "text", "e.region", "Effort", True, default=False),
    Column("track_file", "Track File", "text", "regexp_replace(t.object_key, '^.*/', '')", "Effort", True),
]

TIMELINE_COLUMNS = [
    Column("effort_id", "Effort ID", "int", "e.legacy_daily_effort_id", "Timeline", required=True),
    Column("at", "Date And Time", "datetime", "t.at", "Timeline"),
    Column("kind", "Kind", "text", "t.kind", "Timeline", fix=lambda k: EffortTimeline.KIND_LABELS.get(k, k)),
    Column("detail", "Detail", "text", "t.label", "Timeline"),
    Column("latitude", "Latitude", "float", "t.lat", "Timeline"),
    Column("longitude", "Longitude", "float", "t.lon", "Timeline"),
]

WEATHER_COLUMNS = [
    Column("effort_id", "Effort ID", "int", "e.legacy_daily_effort_id", "Weather", required=True),
    Column("at", "Date And Time", "datetime", "c.condition_datetime", "Weather"),
    Column("beaufort", "Beaufort", "int", "c.beaufort", "Weather"),
    Column("swell_ft", "Swell (ft)", "int", "c.swell_ft", "Weather"),
    Column("cloud_cover_pct", "Cloud Cover (%)", "int", "c.cloud_cover_pct", "Weather"),
    Column("precipitation", "Precipitation", "text", "c.precipitation", "Weather"),
    Column("quality", "Quality", "text", "c.quality", "Weather"),
    Column("visibility_nm", "Visibility (nm)", "float", "c.visibility_nm", "Weather"),
    Column("comments", "Comments", "text", "c.comments", "Weather"),
    Column("latitude", "Latitude", "float", "c.lat", "Weather"),
    Column("longitude", "Longitude", "float", "c.lon", "Weather"),
]

SAMPLE_COLUMNS = [
    Column("sighting_id", "Sighting ID", "int", "s.legacy_sighting_id", "Sample", required=True),
    Column("sample_number", "Sample Number", "text", "sm.sample_number", "Sample"),
    Column("sample_type", "Sample Type", "text", "sm.sample_type", "Sample"),
    Column("species", "Species", "text", "coalesce(sp.common_name, sp.code)", "Sample"),
    Column("preservation", "Preservation", "text", "sm.preservation", "Sample"),
    Column("sampled_by", "Sampled By", "text", "sm.sampled_by", "Sample"),
]

# What a Sighting's page shows of the records attached to it. These sheets have
# no choice of columns: each is that table as the page shows it.
IDENTIFICATION_COLUMNS = [
    Column("sighting_id", "Sighting ID", "int", "s.legacy_sighting_id", required=True),
    Column("crc_id", "CRC ID", "int", 'coalesce(n."CRC ID", i."CRC ID")'),
    Column("field_id", "Field ID", "text", 'i."Field ID"'),
    Column("species", "Species", "text", 'coalesce(n."Species", i."Species")'),
]
TAG_COLUMNS = [
    Column("sighting_id", "Sighting ID", "int", "s.legacy_sighting_id", required=True),
    Column("tag_number", "Tag Number", "text", 'r."Tag#"'),
    Column("tag_type", "Tag Type", "text", 'r."TagType"'),
    Column("deploy_body_location", "Deploy Body Location", "text", 'r."DeployBodyLoc"'),
    Column("deployed", "Deployed", "datetime", 'r."DeployDateTime"'),
    Column("deploy_reaction", "Deploy Reaction", "text", 'r."DeployRxn"'),
    Column("hours_total", "Hours Total", "float", 'r."HoursTotal"'),
    Column("comments", "Comments", "text", 'r."TagComments"'),
]
EVENT_COLUMNS = [
    Column("sighting_id", "Sighting ID", "int", "s.legacy_sighting_id", required=True),
    Column("event_time", "Event Time", "time", 'r."EventTime"'),
    Column("event", "Event", "text", 'r."SightEvent"'),
    Column("field_id", "Field ID", "text", 'r."Field ID"'),
    Column("reaction", "Reaction", "text", 'r."Reaction"'),
    Column("number_reacting", "Number Reacting", "int", 'r."NumReact"'),
    Column("range", "Range", "int", 'r."Range"'),
    Column("comments", "Comments", "text", 'r."SightEventComments"'),
]
OTHER_SPECIES_COLUMNS = [
    Column("sighting_id", "Sighting ID", "int", "s.legacy_sighting_id", required=True),
    Column("species", "Species", "text", 'r."Species"'),
    Column("class", "Class", "text", 'r."Class"'),
    Column("count", "Count", "int", 'r."Count"'),
    Column("comments", "Comments", "text", 'r."Comments"'),
]


# ---------------------------------------------------------------------------
# The plan: the stacked queries as SQL
# ---------------------------------------------------------------------------


def _sql_of(queryset):
    """A queryset's IDs as (SQL, parameters), to sit inside a bigger query."""
    try:
        sql, params = queryset.order_by().values("pk").query.sql_with_params()
    except EmptyResultSet:
        return "SELECT NULL::bigint WHERE false", []
    return sql, list(params)


class Plan:
    """The stack, turned into the SQL that selects the Efforts and Sightings.

    Each query contributes a subquery of IDs. The Efforts sheet is every
    Effort any query selected, and the same for Sightings, so a record two
    queries both match is in the sheet once.
    """

    def __init__(self, entries):
        self.entries = entries
        self.parts = {"efforts": [], "sightings": []}
        self.querysets = []
        self.broken = []
        for entry in entries:
            try:
                efforts, sightings = export_stack.resolve(entry)
            except export_stack.ExportError as exc:
                self.broken.append((entry, str(exc)))
                efforts = sightings = None
            self.querysets.append((efforts, sightings))
            self.parts["efforts"].append(_sql_of(efforts) if efforts is not None else None)
            self.parts["sightings"].append(_sql_of(sightings) if sightings is not None else None)

    @property
    def multi(self):
        """Two or more queries, which is when Matched Queries is shown."""
        return len(self.entries) >= 2

    def ids(self, which):
        """(SQL, params) of the union of every query's IDs, or None when no
        query gives this kind of record."""
        parts = [p for p in self.parts[which] if p]
        if not parts:
            return None
        sql = " UNION ".join(f"({p[0]})" for p in parts)
        return sql, [v for p in parts for v in p[1]]

    def matched(self, which):
        """One true or false for each query, as SQL on the alias e or s."""
        alias = "e" if which == "efforts" else "s"
        exprs, params = [], []
        for part in self.parts[which]:
            if part:
                exprs.append(f"{alias}.id IN ({part[0]})")
                params += part[1]
            else:
                exprs.append("false")
        return exprs, params

    def query_counts(self):
        """[(Efforts, Sightings)] for each query. None where it gives none."""
        return [(efforts.count() if efforts is not None else None,
                 sightings.count() if sightings is not None else None)
                for efforts, sightings in self.querysets]

    def fetch(self, sql, params=()):
        """Rows from a server-side cursor, a batch at a time."""
        with connection.chunked_cursor() as cur:
            cur.execute(sql, list(params))
            while True:
                batch = cur.fetchmany(BATCH)
                if not batch:
                    return
                yield from batch

    def scalar(self, sql, params=()):
        with connection.cursor() as cur:
            cur.execute(sql, list(params))
            return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------


class Sheet:
    key = title = layout = ""
    columns = []
    geometry = None       # "point" or "line" for a sheet with positions
    geometry_sql = ""     # what selects the position, as well-known binary
    chooser = False       # whether columns can be chosen
    parent = None         # "efforts" or "sightings": whose IDs the sheet follows
    matched = False       # whether Matched Queries applies
    order = ""
    distinct = False
    extras = ()           # values selected after the columns, for convert to use

    # Subclasses give the FROM clause. It uses `ids` for the parent's IDs.
    def source(self, plan):
        """(FROM and WHERE SQL, params), or None when nothing feeds this sheet."""
        raise NotImplementedError

    def convert(self, values, zone):
        """The values after the time zone, in column order. Extras come off."""
        return values

    def meta(self, values):
        return {}

    def count(self, plan):
        source = self.source(plan)
        if source is None:
            return 0
        sql, params = source
        if self.distinct:
            select = ", ".join(c.sql for c in self.columns)
            return plan.scalar(f"SELECT count(*) FROM (SELECT DISTINCT {select} {sql}) q", params)
        return plan.scalar(f"SELECT count(*) {sql}", params)

    def rows(self, plan, zone, limit=None):
        """(values, wkb, meta, matched) for each row, in column order."""
        source = self.source(plan)
        if source is None:
            return
        sql, params = source
        select = [c.sql for c in self.columns] + list(self.extras)
        matched_exprs, matched_params = plan.matched(self.parent) if (plan.multi and self.matched) else ([], [])
        select += matched_exprs
        if self.geometry:
            select.append(self.geometry_sql)
        head = "SELECT DISTINCT " if self.distinct else "SELECT "
        text = f"{head}{', '.join(select)} {sql} ORDER BY {self.order}"
        if limit:
            text += f" LIMIT {int(limit)}"
        width = len(self.columns) + len(self.extras)
        for raw in plan.fetch(text, matched_params + params):
            values = list(raw[:width])
            flags = list(raw[width:width + len(matched_exprs)])
            wkb = raw[-1] if self.geometry else None
            for position, column in enumerate(self.columns):
                if column.fix:
                    values[position] = column.fix(values[position])
            values = self.convert(values, zone)
            yield (values, bytes(wkb) if wkb is not None else None, self.meta(values),
                   [i + 1 for i, flag in enumerate(flags) if flag])


class EffortSheet(Sheet):
    key, title, layout = "efforts", "Efforts", "One row per Effort"
    columns, chooser, geometry, matched, parent = EFFORT_COLUMNS, True, "line", True, "efforts"
    order = "e.effort_date, e.legacy_daily_effort_id"
    geometry_sql = "ST_AsBinary(t.geom)"

    def source(self, plan):
        ids = plan.ids("efforts")
        if ids is None:
            return None
        return (f"FROM app.daily_effort e LEFT JOIN app.vessel v ON v.id = e.vessel_id "
                f"{FIRST_TRACK.format(effort='e')} WHERE e.id IN ({ids[0]})", ids[1])

    def count(self, plan):
        ids = plan.ids("efforts")
        return 0 if ids is None else plan.scalar(
            f"SELECT count(*) FROM app.daily_effort e WHERE e.id IN ({ids[0]})", ids[1])

    def convert(self, values, zone):
        index = {c.key: i for i, c in enumerate(self.columns)}
        day, start, end = (values[index[k]] for k in ("date", "start_time", "end_time"))
        values[index["date"]], values[index["start_time"]] = zone.record_date_time(day, start)
        if end is not None and day is not None:
            # An Effort that ends after midnight ends the next day, which
            # matters once the zone moves its end across a date.
            ends_on = day + datetime.timedelta(days=1) if start is not None and end < start else day
            values[index["end_time"]] = zone.record_date_time(ends_on, end)[1]
        for key in ("track_start", "track_end"):
            values[index[key]] = zone.gps(values[index[key]])
        return values

    def meta(self, values):
        index = {c.key: i for i, c in enumerate(self.columns)}
        parts = [f"Effort {values[index['effort_id']]}", values[index["date"]], values[index["vessel_code"]]]
        return {"name": ", ".join(str(p) for p in parts if p)}


class SightingSheet(Sheet):
    key, title, layout = "sightings", "Sightings", "One row per Sighting"
    columns, chooser, geometry, matched, parent = SIGHTING_COLUMNS, True, "point", True, "sightings"
    order = "s.sighting_date, s.sighting_time, s.legacy_sighting_id"
    geometry_sql = "ST_AsBinary(s.geom)"
    # The Effort's start time, which moves the Effort Date with the zone.
    extras = ("e.start_time",)

    def source(self, plan):
        ids = plan.ids("sightings")
        if ids is None:
            return None
        return (f"FROM app.sighting s LEFT JOIN app.species sp ON sp.id = s.species_id "
                f"LEFT JOIN app.vessel v ON v.id = s.vessel_id "
                f"LEFT JOIN app.daily_effort e ON e.id = s.daily_effort_id "
                f"{FIRST_TRACK.format(effort='e')} WHERE s.id IN ({ids[0]})", ids[1])

    def count(self, plan):
        ids = plan.ids("sightings")
        return 0 if ids is None else plan.scalar(
            f"SELECT count(*) FROM app.sighting s WHERE s.id IN ({ids[0]})", ids[1])

    def convert(self, values, zone):
        index = {c.key: i for i, c in enumerate(self.columns)}
        values[index["date"]], values[index["time"]] = zone.record_date_time(values[index["date"]], values[index["time"]])
        values[index["effort_date"]] = zone.record_date_time(values[index["effort_date"]], values.pop())[0]
        return values

    def meta(self, values):
        index = {c.key: i for i, c in enumerate(self.columns)}
        name = values[index["common_name"]] or values[index["species_code"]] or "Sighting"
        when = None
        if values[index["date"]] and values[index["time"]]:
            when = datetime.datetime.combine(values[index["date"]], values[index["time"]])
        return {"name": f"{name} {values[index['sighting_id']]}", "time": when}


class TimelineSheet(Sheet):
    key, title, layout = "timeline", "Timeline", "Conditions and Day Log, keyed by Effort ID"
    columns, chooser, geometry, parent = TIMELINE_COLUMNS, True, "point", "efforts"
    order = "e.effort_date, e.legacy_daily_effort_id, t.at, t.row_key"
    geometry_sql = "ST_AsBinary(t.geom)"

    def source(self, plan):
        ids = plan.ids("efforts")
        if ids is None:
            return None
        # The Sightings on an Effort are on the Sightings sheet, so the Timeline
        # is the weather readings and the log entries.
        return ("FROM app.effort_timeline t JOIN app.daily_effort e ON e.id = t.daily_effort_id "
                f"WHERE t.kind <> 'sighting' AND t.daily_effort_id IN ({ids[0]})", ids[1])

    def convert(self, values, zone):
        values[1] = zone.record(values[1])
        return values


class WeatherSheet(Sheet):
    key, title, layout = "weather", "Weather", "One row per weather reading, keyed by Effort ID"
    columns, chooser, geometry, parent = WEATHER_COLUMNS, True, "point", "efforts"
    order = "e.effort_date, e.legacy_daily_effort_id, c.condition_datetime, c.id"
    geometry_sql = "ST_AsBinary(c.geom)"

    def source(self, plan):
        ids = plan.ids("efforts")
        if ids is None:
            return None
        return ("FROM app.daily_condition c JOIN app.daily_effort e ON e.id = c.daily_effort_id "
                f"WHERE c.daily_effort_id IN ({ids[0]})", ids[1])

    def convert(self, values, zone):
        values[1] = zone.record(values[1])
        return values


class SampleSheet(Sheet):
    key, title, layout = "samples", "Samples", "Keyed by Sighting ID"
    columns, chooser, parent = SAMPLE_COLUMNS, True, "sightings"
    order = "s.sighting_date, s.legacy_sighting_id, sm.sample_number, sm.id"

    def source(self, plan):
        ids = plan.ids("sightings")
        if ids is None:
            return None
        return ("FROM app.sample sm JOIN app.sighting s ON s.id = sm.sighting_id "
                "LEFT JOIN app.species sp ON sp.id = sm.species_id "
                f"WHERE sm.sighting_id IN ({ids[0]})", ids[1])


def _has_something(columns):
    """A condition that drops a row whose shown columns are all empty, as the
    Sighting page does."""
    shown = ", ".join(f"nullif({c.sql}::text, '')" for c in columns if not c.required)
    return f"coalesce({shown}) IS NOT NULL"


class AttachedSheet(Sheet):
    """A table of records attached to a Sighting, as its page shows it."""

    table = ""
    alias = "r"
    extra_join = ""
    parent = "sightings"

    def source(self, plan):
        ids = plan.ids("sightings")
        if ids is None:
            return None
        a = self.alias
        return (f'FROM dbo."{self.table}" {a} JOIN app.sighting s ON s.id = {a}.sighting_id {self.extra_join}'
                f"WHERE {a}.sighting_id IN ({ids[0]}) AND {_has_something(self.columns)}", ids[1])


class IdentificationSheet(AttachedSheet):
    key, title, layout = "identifications", "Identifications", "Keyed by Sighting ID"
    columns, table, alias, distinct = IDENTIFICATION_COLUMNS, "IdentificationT", "i", True
    # The page names the animal from the catalogue of known animals, IndividualT.
    extra_join = 'LEFT JOIN dbo."IndividualT" n ON n."IndividualID" = i."IndividualID" '
    order = "1, 2, 3, 4"


class TagSheet(AttachedSheet):
    key, title, layout = "tags", "Tags", "Keyed by Sighting ID"
    columns, table = TAG_COLUMNS, "TagSummaryT"
    order = "s.sighting_date, s.legacy_sighting_id, r.\"DeployDateTime\", r.\"TagSummaryID\""

    def convert(self, values, zone):
        values[4] = zone.record(values[4])
        return values


class EventSheet(AttachedSheet):
    key, title, layout = "sighting_events", "Sighting Events", "Keyed by Sighting ID"
    columns, table = EVENT_COLUMNS, "SightingEventT"
    # The day the event was logged, which moves the time of day with the zone.
    extras = ('r."EventDateTime"::date',)
    order = 's.sighting_date, s.legacy_sighting_id, r."EventDateTime", r."EventTime", r."SightingEventID"'

    def convert(self, values, zone):
        day = values.pop()
        values[1] = zone.record_date_time(day, values[1])[1]
        return values


class OtherSpeciesSheet(AttachedSheet):
    key, title, layout = "other_species", "Other Species", "Keyed by Sighting ID"
    columns, table = OTHER_SPECIES_COLUMNS, "OtherSpeciesT"
    order = 's.sighting_date, s.legacy_sighting_id, r."OtherSpeciesID"'


SHEETS = [EffortSheet(), SightingSheet(), TimelineSheet(), WeatherSheet(), SampleSheet(), IdentificationSheet(),
          TagSheet(), EventSheet(), OtherSpeciesSheet()]
BY_KEY = {sheet.key: sheet for sheet in SHEETS}
DEFAULT_SHEETS = ("efforts", "sightings")


# ---------------------------------------------------------------------------
# Choosing
# ---------------------------------------------------------------------------


class Choice:
    """What the reader chose: a format, a zone, a date format, which sheets,
    and which columns of each."""

    def __init__(self, fmt="xlsx", zone=UTC, date_format="iso", raw=False, sheets=DEFAULT_SHEETS, columns=None):
        self.format = fmt
        self.date_format = date_format if date_format in ("iso", "excel") else "iso"
        # GPX times are always UTC and GeoPackage dates always ISO, by the
        # formats' own rules, so the choice does not apply to them.
        if fmt == "gpx":
            zone = UTC
        if fmt in ("gpx", "gpkg"):
            self.date_format = "iso"
        self.zone = Zone(zone)
        self.raw = raw
        self.sheets = [s.key for s in SHEETS if s.key in sheets]
        self.columns = columns or {}

    @classmethod
    def from_params(cls, params):
        """Read a query string. Without a format the page has not been
        submitted, so everything is at its default; once it has been, a sheet
        that is not ticked is not wanted. The page sends an empty col_ value
        for each sheet, so a sheet whose columns are all unticked still reads
        as chosen, and one the page never mentioned has its default columns."""
        from .exporters import FORMATS
        if "format" not in params:
            return cls()
        columns = {}
        for sheet in SHEETS:
            if sheet.chooser and params.getlist(f"col_{sheet.key}"):
                columns[sheet.key] = params.getlist(f"col_{sheet.key}")
        fmt = params.get("format")
        return cls(fmt if fmt in FORMATS else "xlsx", params.get("tz", UTC), params.get("df", "iso"),
                   params.get("raw") == "1", params.getlist("sheet"), columns)

    def keys(self, sheet):
        """The column keys written for a sheet, in the order they are defined."""
        if not sheet.chooser or sheet.key not in self.columns:
            return [c.key for c in sheet.columns if c.default]
        wanted = set(self.columns[sheet.key])
        return [c.key for c in sheet.columns if c.required or c.key in wanted]


def shape(sheet, plan, choice, limit=None, zone=None):
    """A sheet as the writers take it, with the chosen columns."""
    zone = zone or choice.zone
    keys = choice.keys(sheet)
    positions = [i for i, c in enumerate(sheet.columns) if c.key in keys]
    chosen = [sheet.columns[i] for i in positions]
    with_matches = plan.multi and sheet.matched
    headers = (["Matched Queries"] if with_matches else []) + [c.label for c in chosen]
    kinds = (["text"] if with_matches else []) + [c.kind for c in chosen]

    def rows():
        for values, wkb, meta, matched in sheet.rows(plan, zone, limit):
            out = [values[i] for i in positions]
            if with_matches:
                out.insert(0, ", ".join(str(n) for n in matched))
            yield out, wkb, meta

    appended = ([False] if with_matches else []) + [c.appended for c in chosen]
    return OutSheet(sheet.title, file_name(sheet.title), headers, kinds, rows(), sheet.geometry, appended)


TRACKS_FOLDER = "tracks"
TRACK_LIST = "track_file_list.csv"


def track_file_count(plan):
    """How many raw GPS files the Efforts in the export have to give."""
    ids = plan.ids("efforts")
    if ids is None:
        return 0
    return plan.scalar("SELECT count(DISTINCT x.object_key) FROM app.track x "
                       "WHERE x.object_key IS NOT NULL AND x.track_status = ANY(%s) "
                       f"AND x.daily_effort_id IN ({ids[0]})", [list(Track.HAS_FILE), *ids[1]])


def _entry_name(key, used):
    """The name a track file has in the tracks folder: its own file name where
    that is a plain name nobody has taken, else the whole key with its slashes
    made underscores, else a numbered name. Never empty, never . or .., and
    never holding a path separator, so it cannot reach outside the folder."""
    key = key.replace("\\", "/").replace("\x00", "")
    for name in (posixpath.basename(key), key.replace("/", "_")):
        name = name.strip()
        if name.strip(".") and name not in used:
            return name
    number = len(used) + 1
    while f"track_file_{number}.csv" in used:
        number += 1
    return f"track_file_{number}.csv"


def track_files(plan):
    """(path in the zip, bytes) for the raw GPS files of every Effort in the
    export, the originals from storage under their own file names, then a list
    saying what happened to each Effort's file.

    An Effort with no track record, a blank track (a file with no points) or a
    file that storage does not hold is left out of the folder and named in the
    list, so nothing goes missing without being said. A file whose name is
    taken, or is not a plain name, is renamed in the folder, and the list gives
    both the name it had and the name it has.
    """
    ids = plan.ids("efforts")
    wanted = [] if ids is None else plan.fetch(
        "SELECT e.legacy_daily_effort_id, x.object_key, x.track_status "
        "FROM app.daily_effort e LEFT JOIN app.track x ON x.daily_effort_id = e.id "
        f"WHERE e.id IN ({ids[0]}) ORDER BY e.effort_date, e.legacy_daily_effort_id, x.legacy_track_id", ids[1])
    wanted = list(wanted)
    stored = track_objects.configured()
    keys = sorted({key for _, key, status in wanted if key and status in Track.HAS_FILE})
    found, used, names = set(), set(), {}
    if stored:
        for key, body in track_objects.fetch(keys):
            name = _entry_name(key, used)
            used.add(name)
            found.add(key)
            names[key] = name
            yield f"{TRACKS_FOLDER}/{name}", body

    out = io.StringIO(newline="")
    listing = csv.writer(out)
    listing.writerow(["Effort ID", "Track File", "Name In The Tracks Folder", "In The Tracks Folder"])
    for effort_id, key, status in wanted:
        if not key:
            result = "No: the Effort has no track file"
        elif status not in Track.HAS_FILE:
            result = "No: the track is blank, with no points"
        elif not stored:
            result = "No: file storage is not set up on this server"
        elif key not in found:
            result = "No: the file is not in file storage"
        else:
            result = "Yes"
        listing.writerow([effort_id, (posixpath.basename(key) or key) if key else "",
                          names.get(key, ""), result])
    yield TRACK_LIST, "\ufeff" + out.getvalue()
