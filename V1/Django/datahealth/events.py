"""
Writing to the server event log, and reading what the pipeline has recorded.

    from datahealth import events
    events.record("export", "download", request=request, message="Excel export", format="xlsx")

`record` never raises. A page that works must not fail because its note in the
log could not be written (the table missing on a fresh machine, the database
down, a transaction already broken), so every failure is logged and swallowed.

Categories and the plain names of the events are listed here so the pages and
the filters say the same thing everywhere.
"""

import datetime
import ipaddress
import json
import logging
import re

from django.db import DatabaseError, connection, transaction

log = logging.getLogger("sedb.events")

CATEGORIES = {
    "auth": "Authentication",
    "export": "Exports",
    "audit": "Data Changes",
    "tracks": "Track Files",
    "pipeline": "Data Pipeline",
    "deploy": "Deploys",
    "server": "Server",
    "admin": "Django Admin",
    "security": "Security",
    "error": "Errors",
    "feedback": "Feedback",
}

# (category, event): (name shown, level). An event not listed is shown by its own
# name, as Info.
EVENTS = {
    ("auth", "login"): ("Signed In", "info"),
    ("auth", "login_failed"): ("Sign-In Failed", "warning"),
    ("auth", "logout"): ("Signed Out", "info"),
    ("export", "download"): ("Export Downloaded", "info"),
    ("export", "failed"): ("Export Failed", "error"),
    ("export", "events_csv"): ("Server Log Downloaded", "info"),
    ("audit", "create"): ("Record Created", "info"),
    ("audit", "update"): ("Record Edited", "info"),
    ("audit", "delete"): ("Record Deleted", "warning"),
    ("audit", "restore"): ("Record Restored", "info"),
    ("audit", "upload"): ("File Uploaded", "info"),
    ("audit", "associate"): ("Track Matched", "info"),
    ("audit", "dissociate"): ("Track Unmatched", "info"),
    ("audit", "edit_file"): ("Track File Edited", "info"),
    ("audit", "undo"): ("Change Undone", "info"),
    ("tracks", "check_recomputed"): ("Track File Check Recomputed", "info"),
    ("tracks", "check_removed"): ("Track File Check Removed", "info"),
    ("tracks", "nightly_check"): ("Nightly Track File Check", "info"),
    ("tracks", "nightly_check_failed"): ("Nightly Track File Check Failed", "error"),
    ("tracks", "geometry_rebuilt"): ("Track Lines Rebuilt", "info"),
    ("pipeline", "published"): ("Pipeline Run Published", "info"),
    ("pipeline", "built"): ("Pipeline Run Built, Not Published", "info"),
    ("pipeline", "failed"): ("Pipeline Run Failed", "error"),
    ("pipeline", "cancelled"): ("Pipeline Run Cancelled", "warning"),
    ("deploy", "deployed"): ("Website Deployed", "info"),
    ("deploy", "failed"): ("Deploy Failed", "error"),
    ("server", "started"): ("Server Started", "info"),
    ("server", "stopped"): ("Server Stopped", "warning"),
    ("server", "slow_request"): ("Slow Request", "warning"),
    ("admin", "added"): ("Admin Added", "info"),
    ("admin", "changed"): ("Admin Changed", "info"),
    ("admin", "deleted"): ("Admin Deleted", "warning"),
    ("security", "access_denied"): ("Access Denied", "warning"),
    ("error", "server_error"): ("Server Error", "error"),
    ("feedback", "submitted"): ("Feedback Sent", "info"),
}

LEVELS = ["info", "warning", "error"]

_SLUG = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

# What a pipeline run's result means for the log (app.pipeline_run.result).
# A result not listed is a failure of one kind or another.
PIPELINE_EVENTS = {
    "published": ("published", "info"),
    "not published": ("built", "info"),
    "cancelled": ("cancelled", "warning"),
}


def event_label(category, event):
    return EVENTS.get((category, event), (event.replace("_", " ").title(), "info"))[0]


def _address(request):
    """The visitor's address. Behind nginx every request comes from the machine
    itself, and nginx adds the visitor to the end of X-Forwarded-For, so that last
    entry is the one to trust; a visitor can only put names in front of it."""
    if request is None:
        return None
    meta = request.META
    candidates = []
    if meta.get("REMOTE_ADDR") in ("127.0.0.1", "::1"):
        candidates += [part.strip() for part in reversed(meta.get("HTTP_X_FORWARDED_FOR", "").split(","))]
    candidates.append(meta.get("REMOTE_ADDR", ""))
    for text in candidates:
        try:
            return str(ipaddress.ip_address(text))
        except ValueError:
            continue
    return None


def _person(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return "", None
    name = user.get_full_name() if hasattr(user, "get_full_name") else ""
    return name or getattr(user, "username", "") or "unknown", getattr(user, "id", None)


def _safe(details):
    """The details as plain JSON, whatever was passed (dates, Decimals, sets)."""
    return json.loads(json.dumps(details, default=str))


def record(category, event, *, request=None, user=None, level=None, message="", actor=None,
           path=None, occurred_at=None, **details):
    """Add one entry to the log. Returns it, or None when it could not be written."""
    level = level or EVENTS.get((category, event), (None, "info"))[1]
    try:
        who, who_id = _person(user if user is not None else getattr(request, "user", None))
        if actor is not None:
            who, who_id = actor, None
        if path is None and request is not None:
            path = request.path
        fields = dict(
            category=category, event=event, level=level, actor=who[:150], actor_id=who_id,
            ip_address=_address(request), path=(path or "")[:300], message=str(message)[:2000],
            details=_safe(details))
        if occurred_at:
            fields["occurred_at"] = occurred_at
        from .models import ServerEvent
        # A savepoint, so a failure here cannot spoil the transaction the caller is in.
        with transaction.atomic():
            return ServerEvent.objects.create(**fields)
    except Exception:
        log.debug("Could not write %s/%s to the event log", category, event, exc_info=True)
        return None


def valid_slug(text):
    return bool(_SLUG.match(text or ""))


# ---------------------------------------------------------------------------
# The pipeline's own record of its runs
# ---------------------------------------------------------------------------


def pipeline_runs(limit=10):
    """The latest runs of the daily pipeline from app.pipeline_run, newest first, as
    dicts; [] where the table is not there (a database the pipeline has not touched)."""
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT to_regclass('app.pipeline_run') IS NOT NULL")
            if not cur.fetchone()[0]:
                return []
            cur.execute("""
                SELECT run_id, started_at AT TIME ZONE 'UTC', finished_at AT TIME ZONE 'UTC', result,
                       git_commit, run_url, deployment_url, tests_passed, tests_failed
                FROM app.pipeline_run ORDER BY started_at DESC LIMIT %s""", [limit])
            columns = ["run_id", "started_at", "finished_at", "result", "git_commit", "run_url",
                       "report_url", "tests_passed", "tests_failed"]
            runs = [dict(zip(columns, row)) for row in cur.fetchall()]
    except DatabaseError:
        return []
    for run in runs:
        done, began = run["finished_at"], run["started_at"]
        run["duration_seconds"] = int((done - began).total_seconds()) if done and began else None
        run["event"], run["level"] = PIPELINE_EVENTS.get(run["result"], ("failed", "error"))
    return runs


def sync_pipeline_runs():
    """Copy runs of the daily pipeline into the log, once each. Returns how many were added.

    The pipeline records its runs itself, on the GitHub runner, at the end of a run
    (ETL/pipeline_run.py record); the website only reads them. Called when the Event
    Log opens, so a run appears there without the pipeline knowing the log exists.
    """
    from .models import ServerEvent
    try:
        runs = pipeline_runs(limit=200)
        known = set(ServerEvent.objects.filter(category="pipeline").values_list("details__run_id", flat=True))
    except DatabaseError:
        return 0
    added = 0
    for run in runs:
        if run["run_id"] in known:
            continue
        passed, failed = run["tests_passed"], run["tests_failed"]
        tests = "" if passed is None else f" Tests passed: {passed}, failed: {failed or 0}."
        if record("pipeline", run["event"], level=run["level"], actor="GitHub Actions",
                  occurred_at=run["finished_at"] or run["started_at"],
                  message=f"{run['result'].capitalize()}.{tests}",
                  run_id=run["run_id"], result=run["result"], git_commit=run["git_commit"],
                  run_url=run["run_url"], report_url=run["report_url"], tests_passed=passed,
                  tests_failed=failed, duration_seconds=run["duration_seconds"],
                  started_at=run["started_at"]):
            added += 1
    return added


def prune(days):
    """Delete entries older than `days` days. Returns how many."""
    from .models import ServerEvent, utcnow
    cutoff = utcnow() - datetime.timedelta(days=days)
    return ServerEvent.objects.filter(occurred_at__lt=cutoff).delete()[0]


# ---------------------------------------------------------------------------
# In plain words
# ---------------------------------------------------------------------------

RECORD_NAMES = {"SightingT": "Sighting", "DailyEffortT": "Effort", "TrackT": "Track File",
                "DailyConditionT": "Weather Reading", "DailyEventT": "Log Entry", "SampleT": "Sample"}
AUDIT_VERBS = {"create": "created", "update": "edited", "delete": "deleted", "restore": "restored",
               "upload": "uploaded", "associate": "matched", "dissociate": "unmatched",
               "edit_file": "edited the file of", "undo": "undid a change to"}
EXPORT_FORMATS = {"xlsx": "an Excel", "csv": "a CSV", "gpkg": "a GeoPackage", "gpx": "a GPX",
                  "geojson": "a GeoJSON", "kml": "a KML", "shp": "a Shapefile"}
PIPELINE_WORDS = {"published": "The data pipeline ran and published new data.",
                  "built": "The data pipeline ran. The new data was not published.",
                  "cancelled": "The data pipeline run was cancelled."}


def describe(entry):
    """One sentence saying what happened, for someone who does not read logs:
    "Failed sign-in for doug." and not "auth/login_failed [doug@203.0.113.9]".
    The console shows this unless Advanced is on."""
    kind, details = (entry.category, entry.event), entry.details or {}
    who = entry.actor or "Someone"
    if kind == ("auth", "login"):
        return f"{who} signed in."
    if kind == ("auth", "logout"):
        return f"{who} signed out."
    if kind == ("auth", "login_failed"):
        return f"Failed sign-in for {entry.actor or 'an empty name'}."
    if kind == ("export", "download"):
        return f"{who} downloaded {EXPORT_FORMATS.get(details.get('format'), 'an')} export."
    if kind == ("export", "failed"):
        return f"An export by {who} failed."
    if entry.category == "audit":
        verb = AUDIT_VERBS.get(entry.event, "changed")
        table = RECORD_NAMES.get(details.get("table"), "a record")
        record = details.get("record")
        return f"{who} {verb} {table}{f' {record}' if record else ''}."
    if kind == ("tracks", "check_recomputed"):
        found = details.get("problems")
        problems = "" if found is None else " A problem was found." if found else " No problems found."
        return f"Track file {details.get('file') or ''} was checked again.{problems}".replace("  ", " ")
    if kind == ("tracks", "check_removed"):
        return f"The check of track file {details.get('file') or ''} was removed.".replace("  ", " ")
    if kind == ("tracks", "nightly_check"):
        return "The nightly track file check finished."
    if kind == ("tracks", "nightly_check_failed"):
        return "The nightly track file check failed."
    if kind == ("tracks", "geometry_rebuilt"):
        return "The track lines were rebuilt."
    if entry.category == "pipeline":
        return PIPELINE_WORDS.get(entry.event, f"The data pipeline run failed ({details.get('result') or 'failed'}).")
    if kind == ("deploy", "deployed"):
        # Who pushed what, when the deploy said: "Boaxes pushed 3f9c2ab (Fix the export's time zone)."
        commit, subject = str(details.get("commit") or "")[:7], details.get("subject")
        if commit:
            pushed = f"{details.get('pushed_by') or 'Someone'} pushed {commit}" + (f" ({subject})" if subject else "")
            return f"{pushed}. The website was deployed."
        return "A new version of the website was deployed."
    if kind == ("deploy", "failed"):
        return "A deploy of the website failed."
    if kind == ("server", "started"):
        return "The website server started."
    if kind == ("server", "stopped"):
        return "The website server stopped."
    if kind == ("server", "slow_request"):
        seconds = details.get("seconds")
        took = f" took {seconds:g} seconds" if isinstance(seconds, (int, float)) else " was slow"
        return f"A slow page: {entry.path or 'a request'}{took}."
    if entry.category == "admin":
        what = " ".join(str(x) for x in (details.get("model"), details.get("object")) if x) or "a record"
        return f"{who} {entry.event} {what} in the Django admin."
    if kind == ("security", "access_denied"):
        return f"{who} was refused {entry.path or 'a page'}."
    if kind == ("error", "server_error"):
        return f"Something went wrong on {entry.path or 'a page'}" + (f" for {entry.actor}." if entry.actor else ".")
    if kind == ("feedback", "submitted"):
        return f"{who} sent feedback."
    return entry.message or event_label(entry.category, entry.event)
