"""Checks of every GPS file for data that is probably wrong, one JSON file each.

Each file is read and summed up: its points, times, distance and speeds, and
the problems found in it. The summary is written to a JSON file of its own,
named after the track file, in TRACK_CHECKS_DIR (a folder on the server, beside
the application, so a deploy leaves it alone). Nothing goes in the database or
the bucket: every summary can be made again from its file at any time.

A summary is made again whenever its file changes. track_objects calls
refresh() after any GPS file is written, and forget() after one is removed, so
an import, a save, Fill From File, a delete, a restore and an undo are all
covered. Every night at 2am `manage.py check_track_files` goes over the whole
bucket as well, in case anything was missed, and removes the summaries of
files that are gone.

Two things make a track's health anything but Good, each listed as the pairs
of rows it is found between (first row, last row), so the page can choose the
stretch itself:

    speed       Unlikely Speed: two points in time order further apart than
                200 m at more than 40 knots, which no survey vessel does. Two
                rows with the same time more than 200 m apart count too.
    backwards   Misordered Time: a row's time is earlier than the row before
                it, so the line drawn in file order doubles back on itself.

The rest (gaps, repeated rows, the top speed) is there to read, not a problem.
"""

import datetime
import hashlib
import json
import logging
import math
import os
import pathlib

log = logging.getLogger(__name__)

# Made again by the nightly run when this changes, so a change to the rules
# below reaches every summary without anyone asking.
VERSION = 2

FAST_KNOTS = 40
FAST_METRES = 200          # shorter jumps are left out: a second's GPS jitter is not speed
GAP_MINUTES = 30           # the same gap the track's line is cut at (gps/tracks.py)
TOP_SPEED_SECONDS = 60     # the top speed is measured over a minute, so jitter does not count
RANGES_KEPT = 50           # stretches kept for each problem, for the page to link to

EARTH_METRES = 6371008.8
METRES_PER_NM = 1852

# In the order the page lists them.
PROBLEMS = {
    "speed": "Unlikely Speed",
    "backwards": "Misordered Time",
}


# Where the summaries are


def folder():
    """Read on every call, so a test can point it somewhere after import."""
    from django.conf import settings

    return pathlib.Path(settings.TRACK_CHECKS_DIR)


def _path(key):
    base = folder()
    path = (base / (key + ".json")).resolve()
    if base.resolve() not in path.parents or "/" in key or "\\" in key:
        raise ValueError(f"{key!r} is not a file name.")
    return path


def _is_track(key):
    """Only the bucket's own GPS files, not their earlier versions or deleted copies."""
    return key.lower().endswith(".csv") and "/" not in key and not key.startswith("_")


# Reading a file


def _metres(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_METRES * math.asin(min(1.0, math.sqrt(h)))


def _points(text):
    """[(seconds, lat, lon, line number)] in file order, and how many rows could not be read."""
    points, unreadable = [], 0
    for number, line in enumerate(text.split("\n")[1:], 2):
        line = line.rstrip("\r")
        if not line:
            continue
        parts = line.split(",")
        try:
            when = datetime.datetime.fromisoformat(parts[0].strip())
            lat, lon = float(parts[1]), float(parts[2])
        except (ValueError, IndexError):
            unreadable += 1
            continue
        when = when.replace(tzinfo=datetime.timezone.utc)
        points.append((when.timestamp(), lat, lon, number))
    return points, unreadable


def _iso(seconds):
    return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _knots(metres, seconds):
    return metres / seconds * 3600 / METRES_PER_NM


def analyse(text):
    """The summary of one file's text, as a dict ready to be written as JSON."""
    points, unreadable = _points(text)
    out = {
        "version": VERSION, "points": len(points), "unreadable_rows": unreadable,
        "first": None, "last": None, "minutes": 0, "moving_minutes": 0, "distance_nm": 0.0,
        "top_knots": None, "top_knots_rows": None, "average_knots": None,
        "gaps": 0, "longest_gap_minutes": 0, "repeated_rows": 0, "same_time_rows": 0,
        "backwards": {"rows": 0, "worst_seconds": 0, "ranges": []},
        "speed": {"jumps": 0, "fastest_knots": None, "fastest_rows": None, "ranges": []},
        "problems": [],
    }
    if not points:
        return out

    # In file order: rows whose time is earlier than the row before, and rows repeated exactly.
    back = out["backwards"]
    for a, b in zip(points, points[1:]):
        if b[0] < a[0]:
            back["rows"] += 1
            back["worst_seconds"] = max(back["worst_seconds"], round(a[0] - b[0]))
            if len(back["ranges"]) < RANGES_KEPT:
                back["ranges"].append([a[3], b[3]])
        if a[:3] == b[:3]:
            out["repeated_rows"] += 1

    # In time order, as the vessel went: distance, gaps and speeds.
    ordered = sorted(points, key=lambda p: (p[0], p[3]))
    out["first"], out["last"] = _iso(ordered[0][0]), _iso(ordered[-1][0])
    out["minutes"] = round((ordered[-1][0] - ordered[0][0]) / 60, 1)
    gap = GAP_MINUTES * 60
    metres = moving = 0.0
    fast = out["speed"]
    for a, b in zip(ordered, ordered[1:]):
        seconds, step = b[0] - a[0], _metres(a[1:3], b[1:3])
        if seconds == 0:
            out["same_time_rows"] += 1
        if seconds > gap:
            out["gaps"] += 1
            out["longest_gap_minutes"] = max(out["longest_gap_minutes"], round(seconds / 60, 1))
            continue
        metres += step
        moving += seconds
        # Times are to the second, so two rows in the same second may be up to a second apart.
        knots = _knots(step, max(seconds, 1))
        if step > FAST_METRES and knots > FAST_KNOTS:
            # The jump is the stretch between its two rows, whichever comes first in the file.
            jump = sorted([a[3], b[3]])
            fast["jumps"] += 1
            if fast["fastest_knots"] is None or knots > fast["fastest_knots"]:
                fast["fastest_knots"], fast["fastest_rows"] = round(knots, 1), jump
            if len(fast["ranges"]) < RANGES_KEPT:
                fast["ranges"].append(jump)
    fast["ranges"].sort()
    out["distance_nm"] = round(metres / METRES_PER_NM, 2)
    out["moving_minutes"] = round(moving / 60, 1)
    if moving:
        out["average_knots"] = round(_knots(metres, moving), 1)

    # The top speed over a minute or more: from each point to the first one at least a minute later.
    top, top_rows, j = None, None, 0
    for i, a in enumerate(ordered):
        j = max(j, i + 1)
        while j < len(ordered) and ordered[j][0] - a[0] < TOP_SPEED_SECONDS:
            j += 1
        if j == len(ordered):
            break
        b = ordered[j]
        if b[0] - a[0] > gap:
            continue
        knots = _knots(_metres(a[1:3], b[1:3]), b[0] - a[0])
        if top is None or knots > top:
            top, top_rows = knots, sorted([a[3], b[3]])
    if top is not None:
        out["top_knots"], out["top_knots_rows"] = round(top, 1), top_rows

    if fast["jumps"]:
        out["problems"].append({"code": "speed", "label": PROBLEMS["speed"], "ranges": fast["ranges"],
                                "detail": f"{fast['jumps']:,} {'jump' if fast['jumps'] == 1 else 'jumps'} over "
                                          f"{FAST_KNOTS} knots, the fastest {fast['fastest_knots']:,.0f} knots"})
    if back["rows"]:
        out["problems"].append({"code": "backwards", "label": PROBLEMS["backwards"], "ranges": back["ranges"],
                                "detail": f"{back['rows']:,} {'row' if back['rows'] == 1 else 'rows'} earlier than "
                                          f"the row before, by up to {_lasting(back['worst_seconds'])}"})
    return out


def _lasting(seconds):
    if seconds < 60:
        return f"{seconds:.0f} s"
    if seconds < 3600:
        return f"{seconds // 60:.0f} min"
    return f"{seconds // 3600:.0f} h {seconds % 3600 // 60:.0f} min"


# Writing and reading the summaries


def _md5(body):
    return hashlib.md5(body).hexdigest()


def refresh(key, body):
    """Check one file's bytes and write its summary. Returns the summary, or None for a
    key that is not a GPS file of its own (an earlier version, a deleted copy)."""
    if not _is_track(key):
        return None
    summary = analyse(body.decode("utf-8-sig", errors="replace"))
    summary["file"] = key
    summary["md5"] = _md5(body)
    summary["checked_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = _path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    os.replace(part, path)
    return summary


def forget(key):
    """Remove the summary of a file that is no longer in the bucket."""
    if _is_track(key):
        _path(key).unlink(missing_ok=True)


def after_write(key, body):
    """track_objects calls this after writing any file. A check that fails must never
    stop a save, so it is logged and the nightly run makes the summary later."""
    try:
        summary = refresh(key, body)
    except Exception:
        log.exception("Could not check %s", key)
        return
    if summary is not None:
        _log_event("check_recomputed", f"{key} was checked again: "
                   f"{len(summary['problems'])} problem{'s' if len(summary['problems']) != 1 else ''} found.",
                   file=key, problems=[p["code"] for p in summary["problems"]])


def after_remove(key):
    try:
        forget(key)
    except Exception:
        log.exception("Could not remove the check of %s", key)
        return
    if _is_track(key):
        _log_event("check_removed", f"The check of {key} was removed with the file.", file=key)


def _log_event(event, message, **details):
    """One line in the server event log. Never allowed to fail a save (events.record
    swallows its own errors), and the import is here so this module still loads
    where the datahealth app is not installed (the unit tests)."""
    try:
        from datahealth import events
        events.record("tracks", event, message=message, **details)
    except Exception:
        log.debug("Could not log %s", event, exc_info=True)


def read(key):
    """One file's summary, or None when it has not been checked."""
    try:
        return json.loads(_path(key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# Every summary at once, for the explorer's filter. Each process keeps what it has read and
# reads again only the files whose time has changed, so a list is quick and never stale.
_seen = {"folder": None, "files": {}}


def problems(good=False):
    """{track file name: [problem code, ...]} for every checked file with a problem; with
    `good`, every checked file, the good ones with no codes."""
    base = folder()
    if _seen["folder"] != base:
        _seen["folder"], _seen["files"] = base, {}
    files, found = _seen["files"], {}
    try:
        entries = list(os.scandir(base))
    except OSError:
        return {}
    present = set()
    for entry in entries:
        if not entry.name.endswith(".csv.json"):
            continue
        present.add(entry.name)
        stamp = entry.stat().st_mtime_ns
        held = files.get(entry.name)
        if held is None or held[0] != stamp:
            try:
                summary = json.loads(pathlib.Path(entry.path).read_text(encoding="utf-8"))
                codes = [p["code"] for p in summary.get("problems", [])]
            except (OSError, ValueError, KeyError, TypeError):
                codes = []
            held = files[entry.name] = (stamp, codes)
        if held[1] or good:
            found[entry.name[:-len(".json")]] = held[1]
    for gone in set(files) - present:
        del files[gone]
    return found


def check_all(everything=False, report=None):
    """Check every file in the bucket and remove the summaries of files no longer there.

    A file whose bytes and rules are unchanged since its last check is left alone, unless
    `everything` is set: the result would be the same. Returns (checked, unchanged, removed).
    """
    from survey import track_objects

    listing = track_objects.listing()
    checked = unchanged = removed = 0
    for number, (key, (stored, etag, _size)) in enumerate(sorted(listing.items()), 1):
        if not _is_track(key):
            continue
        held = read(key)
        current = not everything and held and held.get("version") == VERSION
        # A file uploaded in one piece has its MD5 as its ETag, so most need not be read at all.
        if current and held.get("md5") == etag:
            unchanged += 1
            continue
        body = track_objects.read(stored)
        if current and held.get("md5") == _md5(body):
            unchanged += 1
        else:
            refresh(key, body)
            checked += 1
        if report and number % 100 == 0:
            report(f"  {number:,} of {len(listing):,} files")
    base = folder()
    if base.is_dir():
        for entry in os.scandir(base):
            if entry.name.endswith(".csv.json") and entry.name[:-len(".json")] not in listing:
                os.remove(entry.path)
                removed += 1
    return checked, unchanged, removed
