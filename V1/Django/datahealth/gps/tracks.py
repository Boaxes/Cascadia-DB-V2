"""
A GPS track file, from the device's CSV to the line on the map.

Everything that happens to a track file happens here, and the same code runs
whichever way the file arrives:

    add_file()     a file imported through the Track File Manager
    save_text()    the editor's text saved as a file's new version
    fill()         a file's points replaced from an uploaded file
    remove()       a track record deleted, its file kept in _deleted/
    blank_files()  a header-only file for every record that has none
    regenerate()   every file already in the bucket, when the rules change
                   (python manage.py regenerate_track_geometry)

Each goes through process(): clean the text, then build the line. A file's line
is therefore the same whether it was uploaded yesterday or regenerated today.
The line is stored once per file in app.track_geometry, which the build never
drops, so a track's geometry changes only when its file is added or someone
regenerates on purpose.

The Django imports are made inside the functions that need them, so the
cleaning and line code can also be loaded outside Django.

Cleaning
--------
    GPS track file cleaning.

    The devices produce one CSV per day, in whatever state they left it. This turns
    any of them into the single shape everything downstream expects:

        datetime_utc,latitude,longitude
        2013-01-04 19:57:19,33.460763487964869,-117.69176004454494

    UTF-8 with no byte order mark, LF endings, no quoting, exactly three columns,
    final line ends with a newline. A file that differs in any of those is wrong
    even if its values are right.

    The rules, all of them systematic across 10.2 million rows:

      G1  Headers normalised. The files use ten different spellings. Columns are
          matched BY NAME, NEVER BY POSITION -- two files carry an unnamed empty
          column in third place, so reading by position pulls the wrong values.
      G2  Timestamps normalised. `:00` is appended where a device recorded only to
          the minute, and a single-digit hour is padded. That second case is quietly
          destructive if missed: it makes every row from midnight onward look
          malformed, so an afternoon of tracking disappears out of the middle of a
          file with no error.
      G3  Rows dropped where the timestamp is blank or impossible, or a coordinate
          is not a number or out of range.
      G4  Rows dropped where longitude is at or east of zero. Cascadia works from
          Alaska to Central America and Hawaii, all of it west of Greenwich.

    Coordinate text is passed through byte for byte. Reading a coordinate into a
    float and writing it back changes the text on a large share of rows.

Lines
-----
    Turning a cleaned GPS file into a track line.

    A file can hold tens of thousands of points, far more than a map needs. Each
    track is stored as a MultiLineString: one line per run of continuous GPS, each
    simplified to points roughly 11 metres apart. The full-resolution file in
    object storage stays untouched and remains the authority for what a track
    looked like.

      G5  A silence longer than TRACK_GAP_MINUTES ends one line and begins another.
          Nothing is drawn across the gap. This is why tracks used to cross land: a
          straight segment bridging an hour of silence is not a path anybody
          recorded. Measured on densely logged tracks, a 30 minute bridge misses
          the real path by 232 m at the median and 2.4 km at the 90th percentile.
"""

import contextlib
import datetime
import math
import re
import zoneinfo


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------

CLEAN_HEADER = "datetime_utc,latitude,longitude"

# G1. Every spelling found across the 1,479 files, lowercased -- plus the
# header this module writes, so that cleaning a cleaned file changes nothing.
# The bucket holds cleaned files, and regenerating reads them back through here.
TIME_NAMES = {"datetimeutc", "datetime", "datetime_utc"}
LAT_NAMES = {"latitude", "lat"}
LON_NAMES = {"longitude", "lon"}

# G4. Cascadia never works east of Greenwich.
MAX_LONGITUDE = 0.0


def normalise_timestamp(value):
    """`YYYY-MM-DD HH:MM:SS`, or None if the value cannot be one."""
    # Parsed rather than length-checked. Ranges are checked because one file
    # counts seconds past 59 while the minute stays fixed, giving values like
    # 16:46:60 that look valid until something tries to read them.
    try:
        date, clock = value.split(" ")
        year, month, day = (int(x) for x in date.split("-"))
        parts = clock.split(":")
        if len(parts) == 2:
            parts.append("0")
        hour, minute, second = (int(x) for x in parts)
    except ValueError:
        return None
    if not (1 <= month <= 12 and 1 <= day <= 31 and 0 <= hour <= 23
            and 0 <= minute <= 59 and 0 <= second <= 59 and year > 1970):
        return None
    return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"


def _columns(header):
    """G1. Where the time, latitude and longitude are, by name."""
    index = {}
    for position, name in enumerate(header.rstrip("\r").split(",")):
        key = name.strip().lower()
        if key in TIME_NAMES and "time" not in index:
            index["time"] = position
        elif key in LAT_NAMES:
            index["lat"] = position
        elif key in LON_NAMES:
            index["lon"] = position
    return index


def _check(parts, index):
    """
    One row's (time, latitude, longitude) as text, or None and a sentence
    saying why the row cannot be used. G2 to G4; the coordinates stay as typed.
    """
    try:
        when = parts[index["time"]].strip()
        latitude = parts[index["lat"]].strip()
        longitude = parts[index["lon"]].strip()
    except (IndexError, KeyError):
        return None, "Needs three values: date and time, latitude, longitude"
    when = normalise_timestamp(when)              # G2, G3
    if when is None:
        return None, "Date and time must look like 2024-09-24 16:05:27"
    try:
        lat, lon = float(latitude), float(longitude)
    except ValueError:
        return None, "Latitude and longitude must be numbers"
    if not abs(lat) <= 90:                        # G3
        return None, f"Latitude {latitude} is outside -90 to 90"
    if not abs(lon) <= 180:
        return None, f"Longitude {longitude} is outside -180 to 180"
    if lon >= MAX_LONGITUDE:                      # G4
        return None, f"Longitude {longitude} must be west of 0 (negative)"
    return (when, latitude, longitude), None


def clean_text(raw_text):
    """The cleaned text of one GPS file, and how many rows were dropped."""
    lines = raw_text.split("\n")
    index = _columns(lines[0])

    out, dropped = [CLEAN_HEADER], 0
    for line in lines[1:]:
        line = line.rstrip("\r")
        if not line:
            continue
        row, _why = _check(line.split(","), index)
        if row is None:
            dropped += 1
            continue
        out.append(",".join(row))

    return "\n".join(out) + "\n", dropped


def line_errors(raw_text):
    """
    [(line number, reason)] for every line clean_text would drop, or for the
    header if it does not name the three columns. Empty when the text is fine
    as it is: what the editor's Save checks before anything is written.
    """
    lines = raw_text.split("\n")
    if len(_columns(lines[0])) < 3:
        return [(1, "The first line must be datetime_utc,latitude,longitude")]
    index = _columns(lines[0])
    found = []
    for number, line in enumerate(lines[1:], 2):
        line = line.rstrip("\r")
        if line:
            _row, why = _check(line.split(","), index)
            if why:
                found.append((number, why))
    return found


def clean_file(path):
    """Read one raw GPS file and return its cleaned text and dropped count."""
    # utf-8-sig strips the byte order mark 159 of the raw files carry.
    with open(path, encoding="utf-8-sig", newline="") as f:
        return clean_text(f.read())


# ---------------------------------------------------------------------------
# Lines
# ---------------------------------------------------------------------------

TRACK_GAP_MINUTES = 30
SIMPLIFY_TOLERANCE = 0.0001   # degrees, about 11 metres


def read_points(cleaned_text):
    """[(lon, lat, when)] from a cleaned file, in file order."""
    points = []
    for line in cleaned_text.split("\n")[1:]:
        if not line:
            continue
        parts = line.split(",")
        if len(parts) < 3:
            continue
        try:
            lat, lon = float(parts[1]), float(parts[2])
        except ValueError:
            continue
        # Longitude was already checked when the file was cleaned.
        if (lat, lon) == (0.0, 0.0) or abs(lat) > 90:
            continue
        points.append((lon, lat, parts[0]))     # x before y, the PostGIS order
    return points


def split_on_gaps(points):
    """Cut the points into runs wherever the GPS went quiet."""
    gap = TRACK_GAP_MINUTES * 60
    runs, current, previous = [], [], None
    for lon, lat, when in points:
        try:
            at = datetime.datetime.fromisoformat(when)
        except ValueError:
            at = None
        if previous and at and (at - previous).total_seconds() > gap:
            runs.append(current)
            current = []
        current.append((lon, lat))
        previous = at or previous
    runs.append(current)
    return [run for run in runs if run]


def simplify(points, tolerance=SIMPLIFY_TOLERANCE):
    """
    Douglas-Peucker on raw degree values as flat coordinates.

    No projection and no geodesic distance: the tolerance is a degree figure
    and the comparison only has to be consistent, not metric.
    """
    if len(points) < 3:
        return points

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    segments = [(0, len(points) - 1)]

    while segments:
        start, end = segments.pop()
        if end <= start + 1:
            continue
        x1, y1 = points[start]
        x2, y2 = points[end]
        dx, dy = x2 - x1, y2 - y1
        span = math.hypot(dx, dy)

        furthest_index, furthest_distance = -1, 0.0
        for i in range(start + 1, end):
            x, y = points[i]
            if span:
                d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / span
            else:
                # The two ends are the same point, so measure to it directly.
                d = math.hypot(x - x1, y - y1)
            if d > furthest_distance:
                # Strictly greater, so the earliest point wins a tie.
                furthest_distance, furthest_index = d, i

        if furthest_distance > tolerance:
            # Strictly greater, so a point exactly at the tolerance is dropped.
            keep[furthest_index] = True
            segments.append((start, furthest_index))
            segments.append((furthest_index, end))

    return [p for p, k in zip(points, keep) if k]


def to_wkt(cleaned_text):
    """
    `SRID=4326;MULTILINESTRING(...)` for one cleaned file, or None.

    A run with fewer than two surviving points is dropped rather than stored as
    a meaningless single point; a track whose runs all fall away has no
    geometry. Coordinates are rounded to 6 decimal places -- about 11
    centimetres, finer than GPS accuracy -- so the stored text is exact rather
    than dependent on how a language formats a float.
    """
    points = read_points(cleaned_text)
    lines = []
    for run in split_on_gaps(points):
        kept = simplify(run)
        if len(kept) >= 2:
            lines.append("(" + ",".join(f"{x:.6f} {y:.6f}" for x, y in kept) + ")")
    if not lines:
        return None, len(points)
    return "SRID=4326;MULTILINESTRING(" + ",".join(lines) + ")", len(points)


# ---------------------------------------------------------------------------
# One file, start to finish
# ---------------------------------------------------------------------------


class Processed:
    """What one GPS file becomes: its cleaned text and its line."""

    def __init__(self, cleaned, dropped, wkt, points, first, last):
        self.cleaned = cleaned      # the text that goes in the bucket
        self.dropped = dropped      # rows cleaning removed
        self.wkt = wkt              # SRID=4326;MULTILINESTRING(...), or None
        self.points = points        # positions kept before simplifying
        self.first = first          # first and last timestamp, or None
        self.last = last


def process(raw_text):
    """Clean one file and build its line. Reads and writes nothing."""
    cleaned, dropped = clean_text(raw_text)
    wkt, points = to_wkt(cleaned)
    times = [line.split(",", 1)[0] for line in cleaned.split("\n")[1:] if line]
    return Processed(cleaned, dropped, wkt, points,
                     times[0] if times else None, times[-1] if times else None)


def save_geometry(cur, key, etag, wkt, points, first=None, last=None):
    """
    Write one file's row in app.track_geometry, replacing any row it had.

    The length is worked out by Postgres from the stored line, exactly as the
    import always has, so a length never depends on how Python rounds. `first`
    and `last` are the file's first and last time (UTC).
    """
    cur.execute("""
        INSERT INTO app.track_geometry
               (object_key, etag, geom, point_count, length_nm, built_at, first_time, last_time)
        SELECT %(key)s, %(etag)s, g, %(points)s,
               round((ST_Length(g::geography) / 1852)::numeric, 3), now(), %(first)s, %(last)s
        FROM   (SELECT ST_GeomFromEWKT(%(wkt)s) AS g) line
        ON CONFLICT (object_key) DO UPDATE
           SET etag = EXCLUDED.etag, geom = EXCLUDED.geom,
               point_count = EXCLUDED.point_count,
               length_nm = EXCLUDED.length_nm, built_at = EXCLUDED.built_at,
               first_time = EXCLUDED.first_time, last_time = EXCLUDED.last_time
    """, {"key": key, "etag": etag, "wkt": wkt, "points": points, "first": first, "last": last})


def length_nm(cur, wkt):
    """A line's length in nautical miles, the way save_geometry stores it."""
    if not wkt:
        return None
    cur.execute("SELECT round((ST_Length(ST_GeomFromEWKT(%s)::geography)"
                " / 1852)::numeric, 3)", [wkt])
    return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# A file added, changed or deleted through the Track File Manager
# ---------------------------------------------------------------------------

PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")


# The largest file, and the largest import batch, the website takes. The biggest
# GPS file in the bucket is under 3 MB, so these leave plenty of room.
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_BATCH_BYTES = 100 * 1024 * 1024


def _megabytes(size):
    return f"{size / (1024 * 1024):,.1f} MB"


def check_size(name, size):
    """Raise ValueError if one file is over the limit."""
    if size > MAX_FILE_BYTES:
        raise ValueError(f"{name} is {_megabytes(size)}, and a track file can be at most "
                         f"{_megabytes(MAX_FILE_BYTES)}. Nothing was changed.")


def check_batch(uploads):
    """Raise ValueError if a batch of files is over the limit, or one of them is."""
    for upload in uploads:
        check_size(upload.name, upload.size)
    total = sum(upload.size for upload in uploads)
    if total > MAX_BATCH_BYTES:
        raise ValueError(f"Those files add up to {_megabytes(total)}, and one import can be at most "
                         f"{_megabytes(MAX_BATCH_BYTES)}. Import fewer files at a time. Nothing was changed.")


class LineErrors(ValueError):
    """Text a Save refused: `errors` is [(line number, reason)]."""

    def __init__(self, errors):
        count = len(errors)
        super().__init__(f"{count:,} line{'s' if count != 1 else ''} need fixing before this can be saved.")
        self.errors = errors


def pacific_date(when):
    """The date in Pacific time of a UTC timestamp, 2024-09-24 16:05:27: the
    day an Effort is recorded on."""
    at = datetime.datetime.fromisoformat(when).replace(tzinfo=datetime.timezone.utc)
    return at.astimezone(PACIFIC).date()


def vessel_code_in(name):
    """The vessel a file name gives: 20240316-ROB-7to1500.csv is ROB."""
    found = re.match(r"\d{8}[-_]([A-Za-z0-9]+)", name)
    return found.group(1).upper() if found else None


def _rows(count):
    """"1 row" or "2 rows", for the sentences the audit log and the page show."""
    return f"{count:,} row" + ("" if count == 1 else "s")


def _decode(raw):
    return raw.decode("utf-8-sig", errors="replace")


def _read_upload(upload):
    check_size(upload.name, upload.size)
    try:
        result = process(_decode(upload.read()))
    except Exception as exc:
        raise ValueError(f"That file could not be read as GPS data: {exc}")
    if result.cleaned.count("\n") <= 1:
        raise ValueError("That file has no usable GPS rows in it.")
    return result


def _status(matched, points):
    """The status a track record has: matched with points, matched without
    (blank), or not matched (a file in storage, whatever it holds)."""
    if matched:
        return "available" if points else "blank"
    return "unassociated"


def _line_values(cur, result, status, clear=False):
    """What a file sets on its track record: all of it one audit entry, the
    length included, so an undo puts every value back. With `clear`, a file
    with no line also clears the old one. StartTime and EndTime are the file's
    first and last time, in UTC, as the website keeps every track time (DB167
    keeps them in Pacific local time; the build converts, and the DB167 script
    converts back)."""
    values = {"track_status": status, "point_count": result.points,
              "StartTime": result.first, "EndTime": result.last}
    if result.wkt:
        values["length_nm"] = length_nm(cur, result.wkt)
        values["geom"] = result.wkt
    elif clear:
        values["length_nm"] = None
        values["geom"] = None
    return values


def geometry_row(cur, key):
    """One file's row in app.track_geometry as a dict, or None. The line is
    kept as text, so the row can be put back as it was."""
    cur.execute("""
        SELECT object_key, etag, ST_AsEWKT(geom), point_count, length_nm, built_at, track_id,
               first_time, last_time
        FROM   app.track_geometry WHERE object_key = %s""", [key])
    row = cur.fetchone()
    if row is None:
        return None
    return dict(zip(("object_key", "etag", "geom", "point_count", "length_nm", "built_at",
                     "track_id", "first_time", "last_time"), row))


@contextlib.contextmanager
def _removed_on_failure(key):
    """A stored file whose record could not be written is taken out again, so
    storage never holds a file the database does not know about."""
    from survey import track_objects
    try:
        yield
    except Exception:
        try:
            track_objects.delete(key)
        except Exception:
            pass
        raise


@contextlib.contextmanager
def _put_back_on_failure(key, body):
    """The same for a file that was replaced: the old text goes back."""
    from survey import track_objects
    try:
        yield
    except Exception:
        try:
            track_objects.restore(key, body)
        except Exception:
            pass
        raise


def _key_for(effort, filename):
    """A file name in the pattern the bucket already uses: date-VESSEL-name. A
    name that already starts that way is kept as it is."""
    from survey import track_objects
    from survey.models import Track

    stem = re.sub(r"[^A-Za-z0-9._() -]+", "_", filename.rsplit("/", 1)[-1]).strip("_ ") or "GPS.csv"
    stem = stem.replace(" ", "_")
    if not stem.lower().endswith(".csv"):
        stem += ".csv"
    if effort is not None and not re.match(r"\d{8}[-_]", stem):
        code = effort.vessel.code if effort.vessel else "UNK"
        key = f"{effort.effort_date:%Y%m%d}-{code}-{stem}"
    else:
        key = stem
    if Track.objects.filter(object_key__iexact=key).exists() or track_objects.exists(key):
        raise ValueError(f"A file called {key} already exists. Rename the file and try again.")
    return key


def preview_upload(upload):
    """What an uploaded file would be, without storing anything: for the
    Import Files pop-up to suggest a match for it."""
    check_size(upload.name, upload.size)
    cleaned, dropped = clean_text(_decode(upload.read()))
    rows = cleaned.split("\n")[1:-1]
    first = rows[0].split(",")[0] if rows else None
    return {"name": upload.name, "points": len(rows), "dropped": dropped, "first": first,
            "last": rows[-1].split(",")[0] if rows else None,
            "date": f"{pacific_date(first):%Y-%m-%d}" if first else None,
            "vessel": vessel_code_in(upload.name)}


def add_file(actor, upload, effort=None):
    """
    Add one uploaded file: clean it, store it, build its line, and create its
    track record. With `effort`, the record is matched to it; with none, it
    matches no Effort. The file, its geometry row and the track record go in
    together: if the database write fails, the file is removed again.

    An Effort has one track file at most, so an Effort that already has a
    track record is refused (trackfix.check_room).

    Returns the track record's TrackID and a sentence saying what happened, or
    raises ValueError with one saying why it could not.
    """
    _check_effort(effort)
    key = _key_for(effort, upload.name)
    result = _read_upload(upload)
    track_id = _store(actor, key, result, effort)
    if effort is None:
        return track_id, f"{key} uploaded. It is not matched to an Effort."
    return track_id, f"{key} uploaded and matched to effort {effort.legacy_daily_effort_id}."


def _check_effort(effort):
    """Raise ValueError unless a file can be added for this Effort (None is fine)."""
    from .. import trackfix

    if effort is not None:
        if not effort.effort_date:
            raise ValueError(f"Effort {effort.legacy_daily_effort_id} has no date to name the file by.")
        trackfix.check_room(effort)


def _store(actor, key, result, effort, comment=None):
    """Store a processed file and create its track record, matched to `effort`
    when there is one. Returns the new TrackID."""
    from django.db import connection, transaction

    from survey import track_objects

    from .. import audit

    etag = track_objects.put(key, result.cleaned.encode("utf-8"))
    with _removed_on_failure(key), transaction.atomic(), connection.cursor() as cur:
        # Past every TrackID there has been, including a deleted track's, which
        # Restore needs to find free.
        cur.execute("""
            SELECT greatest((SELECT coalesce(max("TrackID"), 0) FROM dbo."TrackT"),
                            (SELECT coalesce(max(target_pk::integer), 0) FROM app.audit_log
                             WHERE target_table = 'TrackT'),
                            (SELECT coalesce(max(track_id), 0) FROM app.track_geometry)) + 1""")
        track_id = cur.fetchone()[0]
        values = {"TrackID": track_id, "TrackFileName": key, "file_name": key,
                  "Useable": True, "TrackFileType": "csv"}
        if effort is not None:
            values.update({
                "SurveyDate": effort.effort_date, "EffortID": effort.legacy_daily_effort_id,
                "daily_effort_id": effort.pk, "Research Group": effort.research_group,
                "Vessel": effort.vessel.code if effort.vessel else None,
                "vessel_id": effort.vessel_id})
        else:
            day = re.match(r"(\d{4})(\d\d)(\d\d)", key)
            code = vessel_code_in(key)
            vessel = _vessel_by_code(cur, code)
            values.update({
                "SurveyDate": (f"{day.group(1)}-{day.group(2)}-{day.group(3)}" if day
                               else pacific_date(result.first) if result.first else None),
                "Vessel": code, "vessel_id": vessel})
        values.update(_line_values(cur, result, _status(effort is not None, result.points)))
        save_geometry(cur, key, etag, result.wkt, result.points, result.first, result.last)
        audit.insert(actor, "track", values, uploaded_object=key,
                     comment=comment or f"Uploaded {key}"
                             + (f" for effort {effort.legacy_daily_effort_id}" if effort is not None
                                else ", matched to no Effort")
                             + f": {result.points:,} points kept, {_rows(result.dropped)} dropped "
                               "by cleaning.")
    return track_id


# The note on the audit entry of a track made from an Effort's positions: the
# only mark such a track carries.
POSITIONS_COMMENT = ("Created from the Effort's recorded positions "
                     "(log entries, weather readings and sightings).")


def positions_text(rows):
    """
    The clean file text for an Effort's recorded positions: `rows` is (time,
    latitude, longitude) in time order, from the effort_timeline view, whose
    times are UTC. A row with no time or no position is left out.
    """
    out = [CLEAN_HEADER]
    for at, lat, lon in rows:
        if at is None or lat is None or lon is None:
            continue
        if at.tzinfo is not None:
            at = at.astimezone(datetime.timezone.utc)
        out.append(f"{at:%Y-%m-%d %H:%M:%S},{float(lat):.6f},{float(lon):.6f}")
    return "\n".join(out) + "\n"


def positions_key(effort):
    """The file name an Effort's track made from positions gets, named as an import
    names its files. Raises ValueError if that name is taken."""
    return _key_for(effort, f"{effort.legacy_daily_effort_id}.csv")


def add_text(actor, text, effort, comment=None):
    """
    Add a track file from text the person has in the editor, for `effort`: the
    same as add_file, from the text instead of an upload. The text is checked
    as Save checks it (line_errors), so nothing is written if any line is wrong.

    Returns the TrackID and a sentence, or raises LineErrors or ValueError.
    """
    _check_effort(effort)
    key = positions_key(effort)
    check_size(key, len(text.encode("utf-8")))
    errors = line_errors(text)
    if errors:
        raise LineErrors(errors)
    result = process(text)
    if result.cleaned.count("\n") <= 1:
        raise ValueError("There are no usable GPS rows to save.")
    track_id = _store(actor, key, result, effort, comment=comment or POSITIONS_COMMENT)
    return track_id, f"{key} created and matched to effort {effort.legacy_daily_effort_id}."


def _vessel_by_code(cur, code):
    """The vessel_id of a vessel code, or None."""
    if not code:
        return None
    cur.execute("SELECT id FROM app.vessel WHERE upper(code) = %s ORDER BY id LIMIT 1", [code])
    row = cur.fetchone()
    return row[0] if row else None


def save_text(actor, track, text, comment=None):
    """
    Save the whole text of a track file, as the editor shows it.

    The text is checked first (line_errors); nothing is written if any line is
    wrong. The old file is kept in _versions/ (survey/track_objects.replace),
    the file's line and counts are worked out again, and one audit entry,
    edit_file, names the version kept. Fifty edits in the editor and one Save
    are one version.

    Returns a sentence, or raises LineErrors or ValueError.
    """
    from django.db import connection, transaction

    from survey import track_objects

    from .. import audit

    key = track.object_key
    if not key:
        raise ValueError("This track has no file name, so there is no file to save.")
    check_size(key, len(text.encode("utf-8")))
    errors = line_errors(text)
    if errors:
        raise LineErrors(errors)
    result = process(text)
    current = track_objects.get(key)
    if (current is None and result.points == 0) or \
            (current is not None and _decode(current) == result.cleaned):
        raise ValueError("Nothing has changed, so there is nothing to save.")

    status = _status(track.daily_effort_id, result.points)
    if current is None:
        etag, version = track_objects.put(key, result.cleaned.encode("utf-8")), None
        protect = _removed_on_failure(key)
    else:
        etag, version = track_objects.replace(key, result.cleaned)
        protect = _put_back_on_failure(key, current)
    with protect, transaction.atomic(), connection.cursor() as cur:
        before = geometry_row(cur, key)
        save_geometry(cur, key, etag, result.wkt, result.points, result.first, result.last)
        snapshot = ({"uploaded_object": key} if current is None else
                    {"track_geometry": before,
                     "storage": {"restore_version": {"key": key, "version": version}}})
        audit.update(actor, "track", track.legacy_track_id,
                     _line_values(cur, result, status, clear=True), action="edit_file",
                     extra_changes={"version": {"old": None, "new": version}},
                     snapshot=snapshot,
                     comment=comment or f"Saved {key}: {result.points:,} points.")
    return f"Saved. {result.points:,} points. The earlier version is kept in History."


def fill_preview(track, upload):
    """
    Fill From File, step one: the uploaded file beside the current one, and
    nothing written. Returns both texts' figures and lines for the pop-up.
    """
    from survey import track_objects

    result = _read_upload(upload)
    current = track_objects.get(track.object_key) if track.object_key else None
    return {"name": upload.name, "dropped": result.dropped,
            "current": summarise(_decode(current) if current else CLEAN_HEADER + "\n"),
            "new": summarise(result.cleaned)}


def fill(actor, track, upload):
    """Fill From File, step two: the uploaded file's points replace the file's."""
    result = _read_upload(upload)
    return save_text(actor, track, result.cleaned,
                     comment=f"Filled {track.object_key} from {upload.name}: {result.points:,} points "
                             f"kept, {_rows(result.dropped)} dropped by cleaning.")


def summarise(text, limit=4000):
    """What the Fill From File pop-up shows of one text: the number of points,
    the first and last time, the length in nautical miles, the lines with
    errors, and the points (thinned to `limit`) for a map."""
    errors = line_errors(text)
    points = []
    for line in text.split("\n")[1:]:
        found = line.split(",")
        if len(found) == 3:
            try:
                points.append((float(found[1]), float(found[2]), found[0]))
            except ValueError:
                pass
    miles = 0.0
    for a, b in zip(points, points[1:]):
        p = math.pi / 180
        x = (math.sin((b[0] - a[0]) * p / 2) ** 2
             + math.cos(a[0] * p) * math.cos(b[0] * p) * math.sin((b[1] - a[1]) * p / 2) ** 2)
        miles += 2 * 3440.065 * math.asin(math.sqrt(x))
    step = max(1, len(points) // limit)
    return {"points": len(points), "first": points[0][2] if points else None,
            "last": points[-1][2] if points else None, "nm": round(miles, 1),
            "errors": len(errors), "line": [[p[0], p[1]] for p in points[::step]]}


def remove(actor, track):
    """
    Delete a track record, keeping everything needed to bring it back.

    The record goes through the audit log as a delete, with its geometry row in
    the snapshot, and the file moves to _deleted/<key>/<UTC timestamp>.csv
    rather than being removed. A file another record also names stays where it
    is. Returns a sentence, or raises ValueError.
    """
    from django.db import connection, transaction

    from survey import track_objects
    from survey.models import Track

    from .. import audit

    key = track.object_key
    shared = bool(key) and Track.objects.filter(object_key__iexact=key).exclude(pk=track.pk).exists()
    move = bool(key) and not shared and track_objects.exists(key)
    destination = track_objects.stamped(track_objects.DELETED, key) if move else None
    with transaction.atomic(), connection.cursor() as cur:
        extra = {}
        if move:
            extra["track_geometry"] = geometry_row(cur, key)
            extra["storage"] = {"restore_deleted": {"key": key, "from": destination}}
        audit.delete(actor, "track", track.legacy_track_id, extra_snapshot=extra,
                     comment=f"Deleted {key or 'track ' + str(track.legacy_track_id)}.")
        if move:
            cur.execute("DELETE FROM app.track_geometry WHERE object_key = %s", [key])
            track_objects.move(key, destination)
    return f"{key or 'The track'} deleted. The file is kept, and Restore brings it back."


def restore_storage(steps):
    """Put a file back where an undone or restored change had it: `steps` is
    the entry's snapshot["storage"] (audit.storage_steps)."""
    from survey import track_objects

    wanted = (steps or {}).get("restore_version")
    if wanted:
        # What is in the bucket now is kept as a version first.
        body = track_objects.get(wanted["version"])
        if body is None:
            raise FileNotFoundError(f"{wanted['version']} is no longer in the bucket.")
        track_objects.keep_version(wanted["key"])
        track_objects.restore(wanted["key"], body)
    wanted = (steps or {}).get("restore_deleted")
    if wanted:
        track_objects.move(wanted["from"], wanted["key"])


def put_back(entry_id, actor=None):
    """
    Undo an Audit Log entry, or with `actor` restore a deleted track, and move
    its file back, as one change: the file moves inside the database
    transaction, so if it cannot move, the database is left as it was and the
    message says nothing changed. Raises ValueError or LookupError with a
    sentence saying why it could not.
    """
    from django.db import transaction

    from survey import track_objects

    from .. import audit

    steps = audit.storage_steps(entry_id)
    try:
        with transaction.atomic():
            if actor is None:
                uploaded = audit.undo(entry_id)
                if uploaded:
                    track_objects.delete(uploaded)
            else:
                audit.restore(actor, entry_id)
            restore_storage(steps)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"The file could not be moved ({exc}), so nothing was changed.") from exc


def blank_files(report=print, dry_run=False):
    """
    A blank file for every track record whose file is not in storage.

    Its text is the header and nothing else, and its row in
    app.track_geometry has no points, so the Track File Manager can open it and
    Fill From File can fill it. Returns the names made (or, with dry_run, the
    names that would be).
    """
    from django.db import connection, transaction

    from survey import track_objects

    with connection.cursor() as cur:
        cur.execute("""SELECT DISTINCT ON (lower(file_name)) file_name FROM dbo."TrackT"
                       WHERE file_name IS NOT NULL AND btrim(file_name) <> ''
                       ORDER BY lower(file_name), file_name""")
        names = [row[0] for row in cur.fetchall()]
    held = {key.lower() for key in track_objects.listing()}
    made = []
    for name in names:
        if name.lower() in held:
            continue
        made.append(name)
        if dry_run:
            continue
        try:
            etag = track_objects.put(name, (CLEAN_HEADER + "\n").encode("utf-8"))
        except (ValueError, FileExistsError) as exc:
            report(f"  skipped {name}: {exc}")
            made.pop()
            continue
        with transaction.atomic(), connection.cursor() as cur:
            save_geometry(cur, name, etag, None, 0)
    return made


# ---------------------------------------------------------------------------
# Every file already in the bucket
# ---------------------------------------------------------------------------


def regenerate(keys=None, dry_run=False, report=print):
    """
    Rebuild the geometry row of every file in the bucket, or of `keys`.

    Each file goes through process() exactly as an upload does. The bucket is
    only read: nothing is uploaded, and nothing but app.track_geometry is
    written. With dry_run, nothing is written at all, and the return value
    says which rows would change.

    Returns {"unchanged": [...], "changed": [...], "added": [...],
             "not_in_bucket": [...]}.
    """
    from django.db import connection, transaction

    from survey import track_objects

    listing = track_objects.listing()
    wanted = sorted(listing) if keys is None else list(keys)
    outcome = {"unchanged": [], "changed": [], "added": [], "not_in_bucket": []}

    with connection.cursor() as cur:
        cur.execute("SELECT object_key, geom::text, point_count, length_nm, first_time::text, last_time::text "
                    "FROM app.track_geometry")
        stored = {r[0]: r[1:] for r in cur.fetchall()}

    for number, key in enumerate(wanted, 1):
        if key not in listing:
            outcome["not_in_bucket"].append(key)
            continue
        stored_key, etag, _ = listing[key]
        text = track_objects.read(stored_key).decode("utf-8-sig", errors="replace")
        result = process(text)
        with connection.cursor() as cur:
            cur.execute("""
                SELECT g::text, round((ST_Length(g::geography) / 1852)::numeric, 3)
                FROM   (SELECT ST_GeomFromEWKT(%s) AS g) line""", [result.wkt])
            geom, length = cur.fetchone()
        fresh = (geom, result.points, length, result.first, result.last)
        if key not in stored:
            outcome["added"].append(key)
        elif stored[key] != fresh:
            outcome["changed"].append(key)
        else:
            outcome["unchanged"].append(key)
        if not dry_run and stored.get(key) != fresh:
            with transaction.atomic(), connection.cursor() as cur:
                save_geometry(cur, key, etag, result.wkt, result.points, result.first, result.last)
        if number % 100 == 0:
            report(f"  {number:,} of {len(wanted):,} files read")
    return outcome
