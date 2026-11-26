"""
The Server page's figures: readings of the machine and the database, kept a
minute apart for the graph, and the few facts shown beside it.

Nothing runs in the background to take the readings. The middleware calls
`maybe_sample` after every request, and it takes one when a minute has passed
since this worker's last. So the graph has a point for every minute the site
was in use, and a gap where nobody was there, which is itself worth seeing.
A week of readings is kept.
"""

import datetime
import sys
import time

from django.conf import settings
from django.db import connection, transaction

from . import events, sysmetrics

SAMPLE_SECONDS = 60
KEEP_DAYS = 7
GRAPH_HOURS = 24

# This worker's last reading: when, and the processor's counters then, so the next
# reading is the average use over the minute between them.
_state = {"next": 0.0, "cpu": None}


def _disk_paths():
    root = "/" if sys.platform != "win32" else settings.BASE_DIR.anchor
    return [("System", root), ("Application", settings.BASE_DIR)]


def _cpu_since_last():
    """Processor use since this worker last asked, in percent; over a tenth of a
    second the first time."""
    now, before = sysmetrics.cpu_times(), _state["cpu"]
    _state["cpu"] = now
    if now is None:
        return None
    if before is None or now[0] <= before[0]:
        return sysmetrics.cpu_percent(0.1)
    total, idle = now[0] - before[0], now[1] - before[1]
    return round(100 * (total - idle) / total, 1)


def database_ms():
    """How long the database takes to answer, in milliseconds; None when it does not."""
    try:
        with connection.cursor() as cur:
            started = time.perf_counter()
            cur.execute("SELECT 1")
            return round((time.perf_counter() - started) * 1000, 2)
    except Exception:
        return None


def reading():
    """The machine and the database right now."""
    memory = sysmetrics.memory()
    disks = sysmetrics.disks(_disk_paths())
    disk = max(disks, key=lambda d: d["percent"], default=None)
    return {"cpu": _cpu_since_last(), "memory": memory and memory["percent"], "disk": disk and disk["percent"],
            "database_ms": database_ms(), "memory_used": memory and memory["used"],
            "memory_total": memory and memory["total"], "disk_free": disk and disk["free"],
            "disk_total": disk and disk["total"], "load": sysmetrics.load_average(),
            "uptime": sysmetrics.uptime_seconds()}


def maybe_sample():
    """Keep a reading if a minute has passed since this worker's last. Never raises."""
    now = time.time()
    if now < _state["next"]:
        return
    _state["next"] = now + SAMPLE_SECONDS
    try:
        from .models import ServerSample, utcnow
        found, minute = reading(), utcnow().replace(second=0, microsecond=0)
        with transaction.atomic():
            ServerSample.objects.bulk_create([ServerSample(
                taken_at=minute, cpu=found["cpu"], memory=found["memory"], disk=found["disk"],
                database_ms=found["database_ms"])], ignore_conflicts=True)
            if minute.minute == 0:
                ServerSample.objects.filter(taken_at__lt=minute - datetime.timedelta(days=KEEP_DAYS)).delete()
    except Exception:
        pass


def samples(hours=GRAPH_HOURS):
    """[[seconds since 1970, processor, memory, disk, database ms], ...] for the graph, oldest first."""
    from .models import ServerSample, utcnow
    since = utcnow() - datetime.timedelta(hours=hours)
    rows = ServerSample.objects.filter(taken_at__gte=since).values_list("taken_at", "cpu", "memory", "disk", "database_ms")
    return [[int(t.replace(tzinfo=datetime.timezone.utc).timestamp()), cpu, memory, disk, ms]
            for t, cpu, memory, disk, ms in rows]


# ---------------------------------------------------------------------------
# The facts beside the graph
# ---------------------------------------------------------------------------


def size_text(value):
    """1536 -> '1.5 KB'."""
    if value is None:
        return "Not Available"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def span_text(seconds):
    """93784 -> '1 day 2 hours': the two largest units, the way people say it."""
    if seconds is None:
        return "Not Available"
    seconds, parts = int(seconds), []
    for name, length in (("day", 86400), ("hour", 3600), ("minute", 60), ("second", 1)):
        count, seconds = divmod(seconds, length)
        if count:
            parts.append(f"{count} {name}{'s' if count != 1 else ''}")
    return " ".join(parts[:2]) or "0 seconds"


def _database_facts():
    out = {}
    for name, sql in (("size", "SELECT pg_database_size(current_database())"),
                      ("connections", "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"),
                      ("limit", "SELECT setting::int FROM pg_settings WHERE name = 'max_connections'")):
        # A savepoint each: one figure the database user may not read must not lose the others.
        try:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(sql)
                out[name] = cur.fetchone()[0]
        except Exception:
            out[name] = None
    return out


def facts(found):
    """[(label, text)] for the list beside the graph, from a reading."""
    from .models import ServerEvent
    database = _database_facts()
    try:
        deploy = ServerEvent.objects.filter(category="deploy").values_list("occurred_at", flat=True).first()
    except Exception:
        deploy = None
    runs = events.pipeline_runs(1)
    connections = (f"{database['connections']} of {database['limit']}"
                   if database["connections"] is not None and database["limit"] else "Not Available")
    return [
        ("Uptime", span_text(found["uptime"])),
        ("Memory", f"{size_text(found['memory_used'])} of {size_text(found['memory_total'])}"
                   if found["memory_total"] else "Not Available"),
        ("Disk", f"{size_text(found['disk_free'])} free of {size_text(found['disk_total'])}"
                 if found["disk_total"] else "Not Available"),
        ("Load Average", " ".join(f"{x:g}" for x in found["load"]) if found["load"] else "Not Available"),
        ("Database Response", "Not Answering" if found["database_ms"] is None else f"{found['database_ms']:g} ms"),
        ("Database Connections", connections),
        ("Database Size", size_text(database["size"])),
        ("Last Deploy", f"{deploy:%b %d, %H:%M} UTC" if deploy else "Not Recorded Yet"),
        ("Last Pipeline Run", f"{runs[0]['result'].capitalize()}, {runs[0]['started_at']:%b %d, %H:%M} UTC"
                              if runs else "Not Recorded Yet"),
    ]
