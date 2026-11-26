"""
The one log on the Server page: everything that happens on the server, in the
order it happened.

Three kinds of thing are read and merged by time:

    the server event log (datahealth/events.py): sign-ins, exports, changes to
        the data, track file checks, deploys, pipeline runs, errors
    log files: the web server's and the database's, named in SERVER_LOG_FILES
    the system journal: the website's own service, the nightly track check, SSH

The page asks for the end of all of them once, then every few seconds for what
is new. What is new is found with a cursor the page hands back: the last event's
id, how far into each file the last read got, and the journal's own cursor. So
a poll reads only what was written since the last one.

Only the files and units listed here are ever read: the cursor names a file by
its key in SERVER_LOG_FILES, never by a path. On the server the website's user
has to be in the `adm` and `systemd-journal` groups to read them (the deploy
sees to it); a file it cannot read is left out, silently, as on a laptop where
none of them exist.

Each line is kept two ways. The plain one is a time and a sentence anyone can
read ("Failed sign-in for doug."), which is what the page shows. The full one
is what Advanced shows: the event's own name, who and from where, and every
detail kept with it, with the system logs' lines among them. An error in a
system log is shown either way.
"""

import datetime
import glob
import json
import os
import re
import shutil
import subprocess

from django.conf import settings

from . import events

# Read from the end of each file when the page opens, and at most this per poll.
OPEN_BYTES = 48 * 1024
POLL_BYTES = 512 * 1024
OPEN_EVENTS = 300
SHOWN = 600
JOURNAL_UNITS = ["sedb", "sedb-track-checks", "ssh"]

DEFAULT_FILES = {
    "nginx": "/var/log/nginx/access.log",
    "nginx-error": "/var/log/nginx/error.log",
    "postgres": "/var/log/postgresql/*.log",
}

MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}

# The time at the start of a line, in the three shapes these logs use, and
# nginx's access log, which keeps its in square brackets.
_STAMP = re.compile(r"^(\d{4})[-/](\d\d)[-/](\d\d)[ T](\d\d):(\d\d):(\d\d)(?:[.,]\d+)?(?: ?(?:UTC|Z|[+-]\d\d:?\d\d))?\s*")
_ACCESS = re.compile(r"\[(\d\d)/(\w{3})/(\d{4}):(\d\d):(\d\d):(\d\d) [+-]\d{4}\] ")
_STATUS = re.compile(r'" (\d{3}) ')
_ERROR = re.compile(r"\b(ERROR|FATAL|PANIC|CRITICAL|Traceback)\b|\[(error|crit|alert|emerg)\]")
_WARNING = re.compile(r"\b(WARNING|WARN)\b|\[warn\]|Failed password|Invalid user")
_JOURNAL_CURSOR = re.compile(r"^[0-9a-z=;]{1,400}$")


def files():
    """{key: path} of the log files to read. A path may be a pattern, for a log
    whose name changes (the database's holds its version); the newest match is read."""
    return getattr(settings, "SERVER_LOG_FILES", None) or DEFAULT_FILES


def _resolve(pattern):
    matches = glob.glob(pattern)
    return max(matches, key=os.path.getmtime) if matches else None


def _level(text):
    status = _STATUS.search(text)
    if status:
        code = status.group(1)
        return "error" if code[0] == "5" else "warning" if code in ("401", "403", "429") else "info"
    return "error" if _ERROR.search(text) else "warning" if _WARNING.search(text) else "info"


def parse(text, fallback):
    """(time, the line without its time) for one line of a log file. A line with no
    time of its own (the rest of a traceback) keeps the time of the line before."""
    found = _STAMP.match(text)
    if found:
        try:
            return datetime.datetime(*map(int, found.groups())), text[found.end():]
        except ValueError:
            return fallback, text
    found = _ACCESS.search(text)
    if found:
        day, month, year, hour, minute, second = found.groups()
        try:
            when = datetime.datetime(int(year), MONTHS[month], int(day), int(hour), int(minute), int(second))
        except (KeyError, ValueError):
            return fallback, text
        return when, text[:found.start()] + text[found.end():]
    return fallback, text


def _line(when, source, level, text, plain=None):
    """One line. `text` is the full line, which Advanced shows. `plain` is what is shown
    otherwise; a line with none (a routine line of a system log, the rest of a
    traceback) is only seen with Advanced on."""
    return {"t": when.strftime("%Y-%m-%d %H:%M:%S"), "src": source, "lv": level, "text": text, "plain": plain}


# ---------------------------------------------------------------------------
# The three sources
# ---------------------------------------------------------------------------


def _events(after):
    """Lines of the event log after an id (or its newest, with no id), and the newest id."""
    from .models import ServerEvent
    try:
        if after is None:
            rows = list(ServerEvent.objects.order_by("-occurred_at", "-id")[:OPEN_EVENTS])[::-1]
            newest = ServerEvent.objects.order_by("-id").values_list("id", flat=True).first() or 0
        else:
            rows = list(ServerEvent.objects.filter(id__gt=after).order_by("id")[:OPEN_EVENTS])
            newest = max([after] + [r.id for r in rows])
    except Exception:
        return [], after or 0
    out = []
    for e in rows:
        who = "@".join(part for part in (e.actor, e.ip_address) if part)
        text = f"{e.category}/{e.event}" + (f" [{who}]" if who else "") + (f" {e.message}" if e.message else "")
        # Everything else the entry holds, as name=value, for Advanced.
        rest = " ".join(f"{name}={json.dumps(value, default=str)}" for name, value in sorted(e.details.items())
                        if name != "traceback" and value not in (None, "", [], {}))
        if e.path:
            rest = f"path={e.path} {rest}".strip()
        out.append(_line(e.occurred_at, "site", e.level, text + (f"  {rest}" if rest else ""), events.describe(e)))
        # An error carries its traceback, which belongs under it as it would in any log.
        for extra in str(e.details.get("traceback", "")).rstrip().splitlines()[-40:]:
            out.append(_line(e.occurred_at, "site", e.level, "    " + extra))
    return out, newest


def _file(key, pattern, held):
    """New lines of one file since `held` ([path, offset]), and where the read got to."""
    path = _resolve(pattern)
    if path is None:
        return [], None
    try:
        size = os.path.getsize(path)
        if held is None or held[0] != path or held[1] > size:
            # Just opened, a new file under the pattern, or the file was rotated.
            start = max(0, size - OPEN_BYTES) if held is None else 0
        else:
            start = held[1]
        start = max(start, size - POLL_BYTES)
        with open(path, "rb") as handle:
            handle.seek(start)
            data = handle.read(size - start)
    except OSError:
        return [], None
    # Only whole lines: a line still being written is left for the next read.
    end = data.rfind(b"\n") + 1
    raw = data[:end].decode("utf-8", errors="replace").splitlines()
    if start and held is None and raw:
        raw = raw[1:]                 # the first line of a read from the middle is cut in half
    out, when = [], datetime.datetime.fromtimestamp(os.path.getmtime(path), datetime.timezone.utc).replace(tzinfo=None)
    parsed = []
    for text in raw:
        stamp, rest = parse(text, None)
        parsed.append((stamp, rest))
    # A first line with no time takes the next line's, not the file's.
    first = next((stamp for stamp, _ in parsed if stamp), when)
    last = first
    for stamp, rest in parsed:
        last = stamp or last
        if rest.strip():
            level = _level(rest)
            # An error in a system log is shown whether or not Advanced is on.
            out.append(_line(last, key, level, rest, f"{key}: {rest.strip()}" if level == "error" else None))
    return out, [path, start + end]


def _journal(cursor):
    """New lines of the system journal for the units above, and its cursor."""
    if shutil.which("journalctl") is None:
        return [], None
    command = ["journalctl", "--no-pager", "-o", "json"]
    for unit in JOURNAL_UNITS:
        command += ["-u", unit]
    command += ["--after-cursor", cursor] if cursor else ["-n", "200"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return [], cursor
    out = []
    for raw in result.stdout.splitlines()[-2000:]:
        try:
            entry = json.loads(raw)
            when = datetime.datetime.fromtimestamp(int(entry["__REALTIME_TIMESTAMP"]) / 1e6, datetime.timezone.utc)
            message = entry.get("MESSAGE", "")
            if not isinstance(message, str):
                continue
            priority = int(entry.get("PRIORITY", 6))
        except (ValueError, KeyError, TypeError):
            continue
        cursor = entry.get("__CURSOR", cursor)
        source = str(entry.get("SYSLOG_IDENTIFIER") or entry.get("_SYSTEMD_UNIT") or "system")[:20]
        level = "error" if priority <= 3 else "warning" if priority == 4 else _level(message)
        out.append(_line(when.replace(tzinfo=None), source, level, message,
                         f"{source}: {message.strip()}" if level == "error" else None))
    return out, cursor


# ---------------------------------------------------------------------------
# Together
# ---------------------------------------------------------------------------


def _held(cursor):
    """The cursor the page sent back, with anything not of the right shape dropped."""
    if not isinstance(cursor, dict):
        return None
    event = cursor.get("e")
    held_files = {}
    for key, value in (cursor.get("f") or {}).items() if isinstance(cursor.get("f"), dict) else ():
        if (key in files() and isinstance(value, list) and len(value) == 2
                and isinstance(value[0], str) and isinstance(value[1], int) and value[1] >= 0):
            held_files[key] = value
    journal = cursor.get("j")
    return {"e": event if isinstance(event, int) and event >= 0 else 0, "f": held_files,
            "j": journal if isinstance(journal, str) and _JOURNAL_CURSOR.match(journal) else None}


def read(cursor=None):
    """(lines oldest first, cursor). With no cursor, the end of every log; with the
    cursor a read returned, only what is new since."""
    held = _held(cursor)
    opening = held is None
    lines, newest = _events(None if opening else held["e"])
    next_cursor = {"e": newest, "f": {}, "j": None}
    for key, pattern in files().items():
        before = None if opening else held["f"].get(key)
        # A file that appears after the page opened is read from its start, not skipped.
        found, where = _file(key, pattern, before if (opening or before) else ["", 0])
        lines += found
        if where:
            next_cursor["f"][key] = where
    found, next_cursor["j"] = _journal(None if opening else held["j"])
    lines += found
    lines.sort(key=lambda line: line["t"])        # stable, so each log keeps its own order
    # Only the routine lines of the system logs are cut to fit: a busy web server
    # must not push the day's sign-ins and exports off the page.
    routine = sum(1 for line in lines if line["plain"] is None)
    drop = max(0, routine - SHOWN)
    kept = []
    for line in lines:
        if line["plain"] is None and drop:
            drop -= 1
            continue
        kept.append(line)
    return kept, next_cursor
