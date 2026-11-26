"""Writing the Export Tool's sheets into a file someone can use.

A sheet arrives here already chosen and in order: its column headings, the
kind of value in each column, and its rows as a generator. Nothing in this
module reads the database, so it can be tested alone, and no writer holds a
whole sheet in memory. Rows are written as they arrive, to a temporary file
that the view then sends.

One rule runs through all of it: empty means empty. The strings NULL, NA and
None never reach a file, because R would read them as data.
"""

import csv
import datetime
import io
import itertools
import json
import re
import shutil
import sqlite3
import struct
import tempfile
import zipfile
from decimal import Decimal
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape

# Excel holds this many rows in a sheet, the heading row included.
EXCEL_MAX_ROWS = 1_048_576

# Written into every export so a file found later still says what it is.
PROVENANCE_NOTE = (
    "Cascadia Research Collective marine mammal survey data. "
    "Effort positions are derived: for most Efforts the position is the "
    "earliest position recorded during the day, not the point of departure."
)

# What each format is, in the words the Export page shows. `holds` is which
# sheets the format can take: all of them, only those with positions, or a list.
FORMATS = {
    "xlsx": {"label": "Excel Workbook (.xlsx)", "extension": "xlsx", "holds": "all",
             "type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             "note": "One workbook with one sheet for each ticked sheet. A sheet longer than "
                     "Excel can hold carries on in another."},
    "csv": {"label": "CSV Files (.zip)", "extension": "zip", "holds": "all", "type": "application/zip",
            "note": "A zip with one CSV file for each ticked sheet."},
    "geojson": {"label": "GeoJSON (.zip)", "extension": "zip", "holds": "positions", "type": "application/zip",
                "note": "A zip with one GeoJSON file for each ticked sheet that has positions. "
                        "Efforts are lines and the rest are points."},
    "gpx": {"label": "GPX (.gpx)", "extension": "gpx", "holds": ("efforts", "sightings"),
            "type": "application/gpx+xml",
            "note": "One GPX file: Efforts as tracks and Sightings as waypoints. Efforts without a "
                    "track are left out. GPX always uses UTC."},
    "gpkg": {"label": "GeoPackage (.gpkg)", "extension": "gpkg", "holds": "positions",
             "type": "application/geopackage+sqlite3",
             "note": "One GeoPackage file with a layer for each ticked sheet that has positions. "
                     "It always uses ISO dates."},
}

DATE_FORMATS = {"iso": "2024-09-24 18:22:03", "excel": "Excel Friendly (9/24/2024 18:22:03)"}

# Control characters that no spreadsheet or XML file may hold.
_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


class OutSheet:
    """One sheet, shaped for writing.

    headers and kinds run side by side. A kind is one of text, int, float,
    bool, date, time or datetime. rows is a generator of (values, wkb, meta):
    the values in column order, the position as well-known binary (or None),
    and a dictionary the GPX writer reads its names and times from.

    geometry is "point" or "line" for a sheet with positions, else None.
    """

    def __init__(self, title, filename, headers, kinds, rows, geometry=None, appended=()):
        self.title = title
        self.filename = filename
        self.headers = headers
        self.kinds = kinds
        self.rows = rows
        self.geometry = geometry
        # Which columns are appended from a related table, for the preview.
        self.appended = appended


# ---------------------------------------------------------------------------
# Time zones
# ---------------------------------------------------------------------------

UTC, PACIFIC = "UTC", "Pacific"
ZONES = (UTC, PACIFIC)


class Zone:
    """The zone every date and time in the file is in: UTC or Pacific.

    The two kinds of time in the database start in different zones. The times
    people recorded (Efforts, Sightings, the Timeline, Weather, Samples, Tags) are
    Pacific time with its daylight saving, as the site shows them. The GPS
    files, and a track's Start and End Time, are UTC. Each is converted to the
    chosen zone, so a file never mixes the two.
    """

    def __init__(self, name):
        self.name = name if name in ZONES else UTC
        self.pacific = ZoneInfo("America/Los_Angeles")

    def record(self, value):
        """A recorded date and time, which is Pacific, in the chosen zone. A
        value at exactly midnight is a date with no time recorded and is left
        alone, rather than being given a time it never had."""
        if self.name == PACIFIC or value is None or value.time() == datetime.time(0):
            return value
        return value.replace(tzinfo=self.pacific).astimezone(datetime.timezone.utc).replace(tzinfo=None)

    def record_date_time(self, day, clock):
        """A recorded date and time of day kept in two columns, moved
        together, so a time that crosses midnight takes its date with it."""
        if self.name == PACIFIC or day is None or clock is None:
            return day, clock
        moved = self.record(datetime.datetime.combine(day, clock))
        return moved.date(), moved.time()

    def gps(self, value):
        """A GPS file's date and time, which is UTC, in the chosen zone."""
        if self.name == UTC or value is None:
            return value
        return value.replace(tzinfo=datetime.timezone.utc).astimezone(self.pacific).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


def format_value(value, kind, date_format="iso"):
    """One cell as text. Empty is an empty string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime.datetime):
        if date_format == "excel":
            return f"{value.month}/{value.day}/{value.year} {value:%H:%M:%S}"
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, datetime.date):
        if date_format == "excel":
            return f"{value.month}/{value.day}/{value.year}"
        return value.isoformat()
    if isinstance(value, datetime.time):
        return value.strftime("%H:%M:%S")
    if isinstance(value, Decimal):
        # No thousands separators and no units, so the column reads as numeric.
        return format(value.normalize(), "f")
    if isinstance(value, float):
        return repr(value)
    return _ILLEGAL.sub("", str(value))


def _json_value(value, kind, date_format):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    return format_value(value, kind, date_format)


def file_name(title):
    """A sheet title as a file name: Sighting Events becomes sighting_events."""
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


# ---------------------------------------------------------------------------
# Positions: well-known binary in, GeoJSON or bounds out
# ---------------------------------------------------------------------------

POINT, LINESTRING, MULTILINESTRING = 1, 2, 5


def point_wkb(lon, lat):
    return struct.pack("<BIdd", 1, POINT, lon, lat)


def _read_wkb(data, offset=0):
    """(type, coordinates, next offset). Points, lines and multi-lines."""
    order = "<" if data[offset] == 1 else ">"
    kind = struct.unpack_from(order + "I", data, offset + 1)[0]
    offset += 5
    if kind == POINT:
        return kind, list(struct.unpack_from(order + "dd", data, offset)), offset + 16
    if kind == LINESTRING:
        count = struct.unpack_from(order + "I", data, offset)[0]
        offset += 4
        flat = struct.unpack_from(order + f"{2 * count}d", data, offset)
        return kind, [list(flat[i:i + 2]) for i in range(0, len(flat), 2)], offset + 16 * count
    if kind == MULTILINESTRING:
        count = struct.unpack_from(order + "I", data, offset)[0]
        offset += 4
        lines = []
        for _ in range(count):
            _kind, line, offset = _read_wkb(data, offset)
            lines.append(line)
        return kind, lines, offset
    raise ValueError(f"Geometry type {kind} cannot be exported.")


def wkb_geometry(data):
    """A GeoJSON geometry for well-known binary."""
    kind, coordinates, _end = _read_wkb(bytes(data))
    name = {POINT: "Point", LINESTRING: "LineString", MULTILINESTRING: "MultiLineString"}[kind]
    return {"type": name, "coordinates": _rounded(coordinates)}


def _rounded(value):
    if isinstance(value, list):
        return [_rounded(v) for v in value]
    return round(value, 7)


def wkb_bounds(data):
    """(min x, min y, max x, max y) of a geometry."""
    kind, coordinates, _end = _read_wkb(bytes(data))
    if kind == POINT:
        coordinates = [coordinates]
    elif kind == MULTILINESTRING:
        coordinates = [c for line in coordinates for c in line]
    xs = [c[0] for c in coordinates]
    ys = [c[1] for c in coordinates]
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------

_EXCEL_NUMBER_FORMATS = {
    "iso": {"datetime": "yyyy-mm-dd hh:mm:ss", "date": "yyyy-mm-dd", "time": "hh:mm:ss"},
    "excel": {"datetime": "m/d/yyyy h:mm:ss", "date": "m/d/yyyy", "time": "h:mm:ss"},
}


def write_xlsx(out, sheets, date_format="iso", note="", max_rows=EXCEL_MAX_ROWS):
    """One workbook, one sheet for each sheet given.

    Written in openpyxl's write-only mode, which streams each sheet to disk
    as it goes. Numbers and dates stay native so Excel treats them as such.
    A sheet longer than Excel can hold carries on in a sheet of the same name
    followed by 2, 3 and so on, with the headings repeated.
    """
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font

    formats = _EXCEL_NUMBER_FORMATS[date_format]
    book = Workbook(write_only=True)
    book.properties.title = "Cascadia Export"
    book.properties.description = f"{PROVENANCE_NOTE} {note}".strip()
    bold = Font(bold=True)

    for sheet in sheets:
        part, ws, written = 0, None, max_rows

        def start(sheet=sheet):
            nonlocal part
            part += 1
            name = sheet.title if part == 1 else f"{sheet.title} {part}"
            ws = book.create_sheet(name[:31])
            ws.freeze_panes = "A2"
            for position, header in enumerate(sheet.headers, 1):
                ws.column_dimensions[_letter(position)].width = min(max(len(header) + 2, 10), 40)
            ws.append([_cell(ws, h, "text", bold, formats, WriteOnlyCell) for h in sheet.headers])
            return ws

        for values, _wkb, _meta in sheet.rows:
            if written >= max_rows - 1:
                ws, written = start(), 0
            ws.append([_cell(ws, v, k, None, formats, WriteOnlyCell)
                       for v, k in zip(values, sheet.kinds)])
            written += 1
        if ws is None:
            start()
    book.save(out)


def _letter(position):
    from openpyxl.utils import get_column_letter
    return get_column_letter(position)


def _cell(ws, value, kind, font, formats, WriteOnlyCell):
    if isinstance(value, Decimal):
        value = float(value)
    elif isinstance(value, str):
        value = _ILLEGAL.sub("", value)
    cell_format = formats.get(kind) if isinstance(value, (datetime.datetime, datetime.date, datetime.time)) else None
    is_formula = isinstance(value, str) and value.startswith("=")
    if font is None and cell_format is None and not is_formula:
        return value
    cell = WriteOnlyCell(ws, value=value)
    if font is not None:
        cell.font = font
    if cell_format:
        cell.number_format = cell_format
    if is_formula:
        # Text that begins with an equals sign is a comment, not a formula.
        cell.data_type = "s"
    return cell


# ---------------------------------------------------------------------------
# CSV and GeoJSON, each file in a zip
# ---------------------------------------------------------------------------


def _entry(archive, name):
    """A text writer for one file in a zip, written as it goes."""
    raw = archive.open(name, "w", force_zip64=True)
    return raw, io.TextIOWrapper(raw, encoding="utf-8-sig" if name.endswith(".csv") else "utf-8", newline="")


def write_csv(archive, sheets, date_format="iso"):
    """CSV with a byte order mark, so Excel opens it as UTF-8."""
    for sheet in sheets:
        raw, text = _entry(archive, f"{sheet.filename}.csv")
        writer = csv.writer(text, lineterminator="\n")
        writer.writerow(sheet.headers)
        for values, _wkb, _meta in sheet.rows:
            writer.writerow([format_value(v, k, date_format) for v, k in zip(values, sheet.kinds)])
        text.flush()
        text.detach()
        raw.close()


def write_geojson(archive, sheets, date_format="iso"):
    """One GeoJSON file for each sheet that has positions.

    A row with no position is written with a null geometry, which GeoJSON
    allows, so the row counts match the other formats.
    """
    for sheet in sheets:
        if not sheet.geometry:
            continue
        raw, text = _entry(archive, f"{sheet.filename}.geojson")
        text.write('{"type": "FeatureCollection", "name": %s, "features": [\n' % json.dumps(sheet.filename))
        for number, (values, wkb, _meta) in enumerate(sheet.rows):
            feature = {
                "type": "Feature",
                "geometry": wkb_geometry(wkb) if wkb else None,
                "properties": {h: _json_value(v, k, date_format)
                               for h, v, k in zip(sheet.headers, values, sheet.kinds)},
            }
            text.write(("," if number else "") + json.dumps(feature, ensure_ascii=False) + "\n")
        text.write("]}\n")
        text.flush()
        text.detach()
        raw.close()


# ---------------------------------------------------------------------------
# GPX
# ---------------------------------------------------------------------------


def _xml(value):
    return escape(_ILLEGAL.sub("", str(value)))


def write_gpx(out, sheets, now=None):
    """Sightings as waypoints and Efforts as tracks, in one file.

    GPX times are always UTC, so the sheets are shaped in UTC for it. The
    description of each waypoint and track lists the columns that were chosen.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    text = io.TextIOWrapper(out, encoding="utf-8", newline="\n", write_through=True)
    text.write('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<gpx version="1.1" creator="Cascadia Research Collective" '
               'xmlns="http://www.topografix.com/GPX/1/1">\n'
               f"<metadata><name>Cascadia Export</name><desc>{_xml(PROVENANCE_NOTE)}</desc>"
               f"<time>{now:%Y-%m-%dT%H:%M:%SZ}</time></metadata>\n")
    by_geometry = sorted((s for s in sheets if s.geometry), key=lambda s: s.geometry != "point")
    for sheet in by_geometry:
        for values, wkb, meta in sheet.rows:
            if not wkb:
                continue
            description = "; ".join(
                f"{h}: {format_value(v, k)}" for h, v, k in zip(sheet.headers, values, sheet.kinds)
                if v is not None and v != "")
            name = _xml(meta.get("name", ""))
            if sheet.geometry == "point":
                lon, lat = _read_wkb(bytes(wkb))[1]
                when = meta.get("time")
                text.write(f'<wpt lat="{lat:.7f}" lon="{lon:.7f}">'
                           + (f"<time>{when:%Y-%m-%dT%H:%M:%SZ}</time>" if when else "")
                           + f"<name>{name}</name><desc>{_xml(description)}</desc></wpt>\n")
            else:
                _kind, lines, _end = _read_wkb(bytes(wkb))
                text.write(f"<trk><name>{name}</name><desc>{_xml(description)}</desc>")
                for line in lines:
                    text.write("<trkseg>" + "".join(
                        f'<trkpt lat="{lat:.7f}" lon="{lon:.7f}"/>' for lon, lat in line) + "</trkseg>")
                text.write("</trk>\n")
    text.write("</gpx>\n")
    text.flush()
    text.detach()


# ---------------------------------------------------------------------------
# GeoPackage
# ---------------------------------------------------------------------------

_WGS84 = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,'
    'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,'
    'AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
    'AUTHORITY["EPSG","4326"]]')

_GPKG_TYPES = {"text": "TEXT", "int": "INTEGER", "float": "REAL", "bool": "BOOLEAN",
               "date": "DATE", "datetime": "DATETIME", "time": "TEXT"}
_GPKG_GEOMETRY = {"point": "POINT", "line": "MULTILINESTRING"}

BATCH = 2000


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _gpkg_value(value, kind, utc):
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S") + ("Z" if utc else "")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, datetime.time):
        return value.strftime("%H:%M:%S")
    if isinstance(value, str):
        return _ILLEGAL.sub("", value)
    return value


def write_gpkg(path, sheets, utc=True):
    """One GeoPackage with a layer for each sheet that has positions.

    Written with the standard library's sqlite3, to the GeoPackage 1.3 layout:
    the three required tables, then one feature table for each layer. The
    positions are the well-known binary PostGIS gave, behind the GeoPackage
    header. Rows go in a batch at a time.
    """
    db = sqlite3.connect(path)
    try:
        db.executescript("""
            PRAGMA application_id = 1196444487;
            PRAGMA user_version = 10300;
            CREATE TABLE gpkg_spatial_ref_sys (
                srs_name TEXT NOT NULL, srs_id INTEGER PRIMARY KEY, organization TEXT NOT NULL,
                organization_coordsys_id INTEGER NOT NULL, definition TEXT NOT NULL, description TEXT);
            CREATE TABLE gpkg_contents (
                table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL, identifier TEXT UNIQUE,
                description TEXT DEFAULT '',
                last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE, srs_id INTEGER,
                CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id));
            CREATE TABLE gpkg_geometry_columns (
                table_name TEXT NOT NULL, column_name TEXT NOT NULL, geometry_type_name TEXT NOT NULL,
                srs_id INTEGER NOT NULL, z TINYINT NOT NULL, m TINYINT NOT NULL,
                CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
                CONSTRAINT uk_gc_table_name UNIQUE (table_name),
                CONSTRAINT fk_gc_tn FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name),
                CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys (srs_id));
        """)
        db.executemany("INSERT INTO gpkg_spatial_ref_sys VALUES (?, ?, ?, ?, ?, ?)", [
            ("Undefined Cartesian SRS", -1, "NONE", -1, "undefined", "undefined Cartesian coordinate reference system"),
            ("Undefined geographic SRS", 0, "NONE", 0, "undefined", "undefined geographic coordinate reference system"),
            ("WGS 84", 4326, "EPSG", 4326, _WGS84, "longitude/latitude coordinates in decimal degrees on the WGS 84 spheroid"),
        ])

        for sheet in sheets:
            if not sheet.geometry:
                continue
            table = sheet.filename
            names = _unique_names(sheet.headers)
            columns = ", ".join(f"{_quote(n)} {_GPKG_TYPES[k]}" for n, k in zip(names, sheet.kinds))
            db.execute(f"CREATE TABLE {_quote(table)} (fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "
                       f"geom {_GPKG_GEOMETRY[sheet.geometry]}{', ' if columns else ''}{columns})")
            insert = (f"INSERT INTO {_quote(table)} (geom{''.join(', ' + _quote(n) for n in names)}) "
                      f"VALUES (?{', ?' * len(names)})")
            bounds = None
            rows = iter(sheet.rows)
            while True:
                batch = list(itertools.islice(rows, BATCH))
                if not batch:
                    break
                prepared = []
                for values, wkb, _meta in batch:
                    geometry = None
                    if wkb:
                        # The header: GP, version 0, flags (little endian), SRS id.
                        geometry = b"GP\x00\x01" + struct.pack("<i", 4326) + bytes(wkb)
                        box = wkb_bounds(wkb)
                        bounds = box if bounds is None else (
                            min(bounds[0], box[0]), min(bounds[1], box[1]),
                            max(bounds[2], box[2]), max(bounds[3], box[3]))
                    prepared.append([geometry] + [_gpkg_value(v, k, utc) for v, k in zip(values, sheet.kinds)])
                db.executemany(insert, prepared)
            db.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, "
                       "min_x, min_y, max_x, max_y, srs_id) VALUES (?, 'features', ?, ?, ?, ?, ?, ?, 4326)",
                       (table, table, sheet.title, *(bounds or (None,) * 4)))
            db.execute("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', ?, 4326, 0, 0)",
                       (table, _GPKG_GEOMETRY[sheet.geometry]))
        db.commit()
    finally:
        db.close()


def _unique_names(headers):
    seen, names = set(), []
    for header in headers:
        name, n = header, 1
        while name.lower() in seen or name.lower() in ("fid", "geom"):
            n += 1
            name = f"{header} {n}"
        seen.add(name.lower())
        names.append(name)
    return names


# ---------------------------------------------------------------------------
# One export, start to finish
# ---------------------------------------------------------------------------

# Formats whose own file is a zip.
ZIPPED = ("csv", "geojson")


def write_export(fmt, sheets, out, date_format="iso", utc=True, note="", track_files=None,
                 max_rows=EXCEL_MAX_ROWS):
    """Write the sheets in one format to `out`, a binary file.

    track_files is a generator of (path, bytes) for the raw GPS files and the
    list that names them, or None. Asking for them turns any format into a zip
    with the files beside the data, because the point of the export is that an
    analyst gets the positions and the GPS behind them together. Returns how
    many of those files it wrote.
    """
    if fmt not in FORMATS:
        raise ValueError(f"Unknown format {fmt}.")
    zipped = fmt in ZIPPED or track_files is not None

    if not zipped:
        _write_single(fmt, sheets, out, date_format, utc, note, max_rows)
        return 0

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        if fmt == "csv":
            write_csv(archive, sheets, date_format)
        elif fmt == "geojson":
            write_geojson(archive, sheets, date_format)
        else:
            with tempfile.TemporaryFile() as single:
                _write_single(fmt, sheets, single, date_format, utc, note, max_rows)
                single.seek(0)
                with archive.open(f"cascadia_export.{FORMATS[fmt]['extension']}", "w", force_zip64=True) as member:
                    shutil.copyfileobj(single, member)
        written = 0
        for path, body in track_files or ():
            archive.writestr(path, body)
            written += 1
        return written


def _write_single(fmt, sheets, out, date_format, utc, note, max_rows):
    if fmt == "xlsx":
        write_xlsx(out, sheets, date_format, note, max_rows)
    elif fmt == "gpx":
        write_gpx(out, sheets)
    else:
        # sqlite3 needs a path, so the file is made beside it and copied in.
        with tempfile.NamedTemporaryFile(suffix=".gpkg") as scratch:
            write_gpkg(scratch.name, sheets, utc)
            with open(scratch.name, "rb") as made:
                shutil.copyfileobj(made, out)
