"""Turning a filtered queryset into a file someone can use without cleanup.

The rule the whole module follows: one row per record, one value per cell,
foreign keys resolved to values, and nothing that needs preparing before
`read.csv()` will do the right thing.
"""

import csv
import datetime
import io
import json
from decimal import Decimal

from django.http import HttpResponse

# Written into every export so a file found later still says what it is.
PROVENANCE_NOTE = (
    "Cascadia Research Collective marine mammal survey data. "
    "Effort positions are derived: for most efforts the position is the "
    "earliest position recorded during the day, not the point of departure."
)


# ---------------------------------------------------------------------------
# Column definitions
#
# Each entry is (column_name, how_to_read_it). Names are snake case and match
# the database, so nothing needs renaming in R.
# ---------------------------------------------------------------------------

SIGHTING_COLUMNS = [
    ("legacy_sighting_id", lambda s: s.legacy_sighting_id),
    ("legacy_daily_effort_id", lambda s: s.daily_effort.legacy_daily_effort_id if s.daily_effort else None),
    ("sighting_date", lambda s: s.sighting_date),
    ("sighting_time", lambda s: s.sighting_time),
    ("sighting_number", lambda s: s.sighting_number),
    ("species_code", lambda s: s.species.code if s.species else None),
    ("species_common_name", lambda s: s.species.common_name if s.species else None),
    ("species_scientific_name", lambda s: s.species.scientific_name if s.species else None),
    ("species_category", lambda s: s.species.category if s.species else None),
    ("species_uncertain", lambda s: s.species_uncertain),
    ("species_raw", lambda s: s.species_raw),
    ("lat", lambda s: s.lat),
    ("lon", lambda s: s.lon),
    ("end_lat", lambda s: s.end_lat),
    ("end_lon", lambda s: s.end_lon),
    ("position_type", lambda s: s.position_type),
    ("sight_type", lambda s: s.sight_type),
    ("est_size_best", lambda s: s.est_size_best),
    ("est_size_min", lambda s: s.est_size_min),
    ("est_size_max", lambda s: s.est_size_max),
    ("num_calves", lambda s: s.num_calves),
    ("group_behavior", lambda s: s.group_behavior),
    ("group_type", lambda s: s.group_type),
    ("depth_m", lambda s: s.depth_m),
    ("photos_taken", lambda s: s.photos_taken),
    ("identified_individual_count", lambda s: s.identified_individual_count),
    ("vessel_code", lambda s: s.vessel.code if s.vessel else None),
    ("vessel_name", lambda s: s.vessel.name if s.vessel else None),
    ("region", lambda s: s.daily_effort.region if s.daily_effort else None),
    ("locality", lambda s: s.daily_effort.locality if s.daily_effort else None),
    ("comments", lambda s: s.comments),
]

EFFORT_COLUMNS = [
    ("legacy_daily_effort_id", lambda e: e.legacy_daily_effort_id),
    ("effort_date", lambda e: e.effort_date),
    ("start_time", lambda e: e.start_time),
    ("end_time", lambda e: e.end_time),
    ("vessel_code", lambda e: e.vessel.code if e.vessel else None),
    ("vessel_name", lambda e: e.vessel.name if e.vessel else None),
    ("locality", lambda e: e.locality),
    ("region", lambda e: e.region),
    ("sub_area", lambda e: e.sub_area),
    ("survey_type", lambda e: e.survey_type),
    ("launch", lambda e: e.launch),
    ("return_location", lambda e: e.return_location),
    ("project_objective", lambda e: e.project_objective),
    ("personnel", lambda e: e.personnel),
    ("total_survey_effort_hours", lambda e: _hours(e.total_survey_effort)),
    ("time_off_effort_hours", lambda e: _hours(e.time_off_effort)),
    ("distance_recorded_nm", lambda e: e.distance_recorded_nm),
    ("start_lat", lambda e: e.start_lat),
    ("start_lon", lambda e: e.start_lon),
    ("start_coord_source", lambda e: e.start_coord_source),
    ("start_position_is_departure_point", lambda e: e.position_is_departure_point),
    ("research_group", lambda e: e.research_group),
    ("survey_comments", lambda e: e.survey_comments),
]

# Detail offered as named checkboxes rather than always present, because most
# exports do not want it. V1 read these out of a JSON blob; they are ordinary
# columns now.
OPTIONAL_SIGHTING_FIELDS = [
    ("bearing", "Bearing to the group"),
    ("range_m", "Range to the group"),
    ("reticle", "Reticle reading"),
    ("range_source", "How range was measured"),
    ("photo_series_1", "First photo series"),
    ("photo_frames_1", "First photo frame range"),
    ("photographer_1", "First photographer"),
]


def _hours(delta):
    """A duration as decimal hours, which survives a CSV where a timedelta
    does not."""
    if delta is None:
        return None
    return round(delta.total_seconds() / 3600, 3)


def columns_for(area, optional_fields=()):
    """The columns an export of this area produces, in order."""
    if area == "efforts":
        return list(EFFORT_COLUMNS)

    columns = list(SIGHTING_COLUMNS)
    chosen = set(optional_fields)
    for name, _label in OPTIONAL_SIGHTING_FIELDS:
        if name in chosen:
            columns.append((name, _attribute(name)))
    return columns


def _attribute(name):
    return lambda record: getattr(record, name, None)


# ---------------------------------------------------------------------------
# Value formatting
# ---------------------------------------------------------------------------


def format_value(value):
    """One cell.

    Empty means empty. The strings NULL, NA and None must never reach a file,
    because R would read them as data.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, datetime.time):
        return value.strftime("%H:%M:%S")
    if isinstance(value, Decimal):
        # No thousands separators and no units, so the column reads as numeric.
        return format(value.normalize(), "f")
    if isinstance(value, float):
        return repr(value)
    return str(value)


def rows_for(queryset, columns):
    for record in queryset.iterator(chunk_size=2000):
        yield [reader(record) for _name, reader in columns]


# ---------------------------------------------------------------------------
# Formats
# ---------------------------------------------------------------------------


def csv_response(queryset, columns, filename):
    """CSV with a byte order mark, so Excel opens it as UTF-8.

    The note goes in a sidecar header comment rather than a first data row,
    because a comment row above the header would break read.csv().
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([name for name, _reader in columns])
    for row in rows_for(queryset, columns):
        writer.writerow([format_value(v) for v in row])

    response = HttpResponse(
        buffer.getvalue().encode("utf-8-sig"), content_type="text/csv; charset=utf-8"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    response["X-Export-Note"] = PROVENANCE_NOTE
    response["X-Export-Generated"] = datetime.date.today().isoformat()
    return response


def excel_response(queryset, columns, filename):
    """One sheet, a frozen header row, and a second sheet carrying the note."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    book = Workbook()
    sheet = book.active
    sheet.title = "data"

    sheet.append([name for name, _reader in columns])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"

    for row in rows_for(queryset, columns):
        sheet.append([_excel_value(v) for v in row])

    about = book.create_sheet("about")
    about.append(["Generated", datetime.date.today().isoformat()])
    about.append(["Note", PROVENANCE_NOTE])

    buffer = io.BytesIO()
    book.save(buffer)

    response = HttpResponse(
        buffer.getvalue(),
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    return response


def _excel_value(value):
    """Numbers and dates stay native so Excel treats them as such; everything
    else goes in as text."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float, datetime.date, datetime.time, datetime.datetime)):
        return value
    return str(value)


def geojson_response(queryset, columns, filename, lat_field, lon_field):
    """The same flat attributes, plus geometry.

    Records with no position cannot be written, so they are dropped and
    counted, and the count is reported on the response rather than left for
    someone to notice.
    """
    features = []
    dropped = 0

    readers = dict(columns)
    for record in queryset.iterator(chunk_size=2000):
        lat = getattr(record, lat_field, None)
        lon = getattr(record, lon_field, None)
        if lat is None or lon is None:
            dropped += 1
            continue

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
            "properties": {
                name: _json_value(reader(record)) for name, reader in columns
            },
        })

    payload = {
        "type": "FeatureCollection",
        "generated": datetime.date.today().isoformat(),
        "note": PROVENANCE_NOTE,
        "records_without_position_dropped": dropped,
        "features": features,
    }

    response = HttpResponse(
        json.dumps(payload), content_type="application/geo+json"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}.geojson"'
    response["X-Records-Dropped"] = str(dropped)
    return response


def _json_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    return format_value(value)
