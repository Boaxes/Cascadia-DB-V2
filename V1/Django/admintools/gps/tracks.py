"""
A GPS track file, from the device's CSV to the line on the map.

Everything that happens to a track file happens here, and the same code runs
whichever way the file arrives:

    add()          a file uploaded through the admin panel's track tool
    regenerate()   every file already in the bucket, when the rules change
                   (python manage.py regenerate_track_geometry)

Both go through process(): clean the text, then build the line. A file's line
is therefore the same whether it was uploaded yesterday or regenerated today.
The line is stored once per file in raw.track_geometry, which the build never
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


def clean_text(raw_text):
    """The cleaned text of one GPS file, and how many rows were dropped."""
    lines = raw_text.split("\n")

    # G1. Find the columns by name.
    index = {}
    for position, name in enumerate(lines[0].rstrip("\r").split(",")):
        key = name.strip().lower()
        if key in TIME_NAMES and "time" not in index:
            index["time"] = position
        elif key in LAT_NAMES:
            index["lat"] = position
        elif key in LON_NAMES:
            index["lon"] = position

    out, dropped = [CLEAN_HEADER], 0
    for line in lines[1:]:
        line = line.rstrip("\r")
        if not line:
            continue
        parts = line.split(",")
        try:
            when = parts[index["time"]].strip()
            latitude = parts[index["lat"]].strip()
            longitude = parts[index["lon"]].strip()
        except (IndexError, KeyError):
            dropped += 1
            continue

        when = normalise_timestamp(when)          # G2, G3
        if when is None:
            dropped += 1
            continue
        try:
            if abs(float(latitude)) > 90 or abs(float(longitude)) > 180:
                dropped += 1                       # G3
                continue
            if float(longitude) >= MAX_LONGITUDE:
                dropped += 1                       # G4
                continue
        except ValueError:
            dropped += 1                           # G3
            continue

        out.append(f"{when},{latitude},{longitude}")

    return "\n".join(out) + "\n", dropped


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


def save_geometry(cur, key, etag, wkt, points):
    """
    Write one file's row in raw.track_geometry, replacing any row it had.

    The length is worked out by Postgres from the stored line, exactly as the
    import always has, so a length never depends on how Python rounds.
    """
    cur.execute("""
        INSERT INTO raw.track_geometry
               (object_key, etag, geom, point_count, length_nm, built_at)
        SELECT %(key)s, %(etag)s, g, %(points)s,
               round((ST_Length(g::geography) / 1852)::numeric, 3), now()
        FROM   (SELECT ST_GeomFromEWKT(%(wkt)s) AS g) line
        ON CONFLICT (object_key) DO UPDATE
           SET etag = EXCLUDED.etag, geom = EXCLUDED.geom,
               point_count = EXCLUDED.point_count,
               length_nm = EXCLUDED.length_nm, built_at = EXCLUDED.built_at
    """, {"key": key, "etag": etag, "wkt": wkt, "points": points})


def length_nm(cur, wkt):
    """A line's length in nautical miles, the way save_geometry stores it."""
    if not wkt:
        return None
    cur.execute("SELECT round((ST_Length(ST_GeomFromEWKT(%s)::geography)"
                " / 1852)::numeric, 3)", [wkt])
    return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# A file added through the track tool
# ---------------------------------------------------------------------------


def _read_upload(upload):
    raw = upload.read().decode("utf-8-sig", errors="replace")
    try:
        result = process(raw)
    except Exception as exc:
        raise ValueError(f"That file could not be read as GPS data: {exc}")
    if result.cleaned.count("\n") <= 1:
        raise ValueError("That file has no usable GPS rows in it.")
    return result


def _line_values(cur, result, status):
    """What an uploaded file sets on its track record: all of it one audit
    entry, the length included, so an undo puts every value back."""
    values = {"track_status": status, "point_count": result.points,
              "StartTime": result.first, "EndTime": result.last}
    if result.wkt:
        values["length_nm"] = length_nm(cur, result.wkt)
        values["geom"] = result.wkt
    return values


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


def _key_for(effort, filename):
    """A file name in the pattern the bucket already uses: date-VESSEL-name."""
    from survey import track_objects
    from survey.models import Track

    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", filename.rsplit("/", 1)[-1]).strip("_") or "GPS.csv"
    if not stem.lower().endswith(".csv"):
        stem += ".csv"
    code = effort.vessel.code if effort.vessel else "UNK"
    key = f"{effort.effort_date:%Y%m%d}-{code}-{stem}"
    if Track.objects.filter(object_key__iexact=key).exists() or track_objects.exists(key):
        raise ValueError(f"A file called {key} already exists. Rename the file and try again.")
    return key


def add(actor, upload, track=None, effort=None):
    """
    Add one uploaded file: clean it, store it, build its line, and attach it.

    With `track`, the file is the one a track record names but storage does
    not hold. With `effort`, the effort has no track record, and one is
    created for it. The file, its geometry row and the track record's change
    go in together: if the database write fails, the file is removed again.

    Returns a sentence saying what happened, or raises ValueError with one
    saying why it could not.
    """
    from django.db import connection, transaction

    from survey import track_objects

    from .. import audit

    HAS_FILE = ("available", "unassociated")

    if (track is None) == (effort is None):
        raise ValueError("A file is added either for a track or for an effort.")

    if track is not None:
        if track.track_status in HAS_FILE:
            raise ValueError(f"{track.object_key} is already in storage.")
        result = _read_upload(upload)
        try:
            etag = track_objects.put(track.object_key, result.cleaned.encode("utf-8"))
        except FileExistsError:
            raise ValueError(f"{track.object_key} is already in storage. Nothing was overwritten.")
        status = "available" if track.daily_effort_id else "unassociated"
        with _removed_on_failure(track.object_key), transaction.atomic(), \
                connection.cursor() as cur:
            save_geometry(cur, track.object_key, etag, result.wkt, result.points)
            audit.update(actor, "track", track.legacy_track_id,
                         _line_values(cur, result, status),
                         action="upload", uploaded_object=track.object_key,
                         comment=f"Uploaded {track.object_key}: {result.points:,} points kept, "
                                 f"{result.dropped:,} rows dropped by cleaning.")
        return (f"{track.object_key} uploaded: {result.points:,} points kept, "
                f"{result.dropped:,} rows dropped.")

    if not effort.effort_date:
        raise ValueError(f"Effort {effort.legacy_daily_effort_id} has no date to name the file by.")
    key = _key_for(effort, upload.name)
    result = _read_upload(upload)
    etag = track_objects.put(key, result.cleaned.encode("utf-8"))
    with _removed_on_failure(key), transaction.atomic(), connection.cursor() as cur:
        cur.execute('SELECT coalesce(max("TrackID"), 0) + 1 FROM dbo."TrackT"')
        track_id = cur.fetchone()[0]
        values = {"TrackID": track_id, "TrackFileName": key, "file_name": key,
                  "SurveyDate": effort.effort_date, "EffortID": effort.legacy_daily_effort_id,
                  "Research Group": "CRC", "Useable": True, "TrackFileType": "csv",
                  "Vessel": effort.vessel.code if effort.vessel else None,
                  "vessel_id": effort.vessel_id}
        values.update(_line_values(cur, result, "available"))
        save_geometry(cur, key, etag, result.wkt, result.points)
        audit.insert(actor, "track", values, uploaded_object=key,
                     comment=f"Uploaded {key} for effort {effort.legacy_daily_effort_id}: "
                             f"{result.points:,} points kept, {result.dropped:,} rows dropped by cleaning.")
    return f"{key} uploaded and linked to effort {effort.legacy_daily_effort_id}."


# ---------------------------------------------------------------------------
# Every file already in the bucket
# ---------------------------------------------------------------------------


def regenerate(keys=None, dry_run=False, report=print):
    """
    Rebuild the geometry row of every file in the bucket, or of `keys`.

    Each file goes through process() exactly as an upload does. The bucket is
    only read: nothing is uploaded, and nothing but raw.track_geometry is
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
        cur.execute("SELECT object_key, geom::text, point_count, length_nm FROM raw.track_geometry")
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
        fresh = (geom, result.points, length)
        if key not in stored:
            outcome["added"].append(key)
        elif stored[key] != fresh:
            outcome["changed"].append(key)
        else:
            outcome["unchanged"].append(key)
        if not dry_run and stored.get(key) != fresh:
            with transaction.atomic(), connection.cursor() as cur:
                save_geometry(cur, key, etag, result.wkt, result.points)
        if number % 100 == 0:
            report(f"  {number:,} of {len(wanted):,} files read")
    return outcome
