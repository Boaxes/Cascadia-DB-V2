"""Cascadia Admin: a dashboard, the Track File Manager, the audit log, and the data
pipeline's documentation. Users and roles are managed in the Django admin."""

from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render


from . import access, audit, audit_labels, db167_script, events, pipeline
from .gps import tracks as gps_tracks

# Cascadia Admin is for people holding the access_data_health permission.
admin_only = access.require("access_data_health")

TABLE_LABELS = {"SightingT": "Sighting", "DailyEffortT": "Effort", "TrackT": "Track File",
                "DailyConditionT": "Weather Reading", "DailyEventT": "Log Entry",
                "SampleT": "Sample"}
ACTION_LABELS = {"update": "Edited", "associate": "Matched", "dissociate": "Unmatched",
                 "upload": "Uploaded", "create": "Created", "delete": "Deleted",
                 "restore": "Restored", "edit_file": "Edited File"}


def _page(request, template, **context):
    context.setdefault("section", "cascadia-admin")
    return render(request, template, context)


# The dashboard


@admin_only
def dashboard(request):
    return _page(request, "datahealth/dashboard.html", tab="dashboard")


# The audit log


def _effort_numbers(changes_list):
    """{internal Effort id: Effort number} for the entries' Effort fields."""
    with connection.cursor() as cur:
        return audit_labels.effort_numbers(cur, audit_labels.effort_ids(changes_list))


def _describe(row, numbers):
    """Plain-English labels and a one-line summary of what changed."""
    row["table_label"] = TABLE_LABELS.get(row["table"], row["table"])
    row["action_label"] = ACTION_LABELS.get(row["action"], row["action"].title())
    fields = [(label, old, new) for label, old, new, name in audit_labels.shown_changes(row.get("changes"), numbers)
              if name != "geom"]
    row["summary"] = "; ".join(
        f"{label}: {_short(old)} to {_short(new)}" for label, old, new in fields[:3]
    ) + ("…" if len(fields) > 3 else "")
    row["db167_label"] = audit.DB167_STATES.get(row.get("db167"), ("", ""))[0]
    number = row.get("number", row["pk"])
    row["link"] = {"SightingT": f"/sightings/{number}/", "DailyEffortT": f"/efforts/{number}/",
                   "TrackT": f"/cascadia-admin/tracks/?open={number}"}.get(row["table"])
    return row


def _short(value):
    if value is None or value == "":
        return "NULL"
    text = str(value)
    return text if len(text) <= 40 else text[:37] + "…"


@admin_only
def audit_log(request):
    """Who changed what, when, and why."""
    rows, total = audit.entries(
        limit=100000, actor=request.GET.get("actor") or None,
        table=request.GET.get("table") or None, action=request.GET.get("action") or None,
        target=(request.GET.get("q") or "").strip() or None,
        db167=request.GET.get("state") or None)
    numbers = _effort_numbers([row.get("changes") for row in rows])
    for row in rows:
        _describe(row, numbers)
    # As many changes as fit the window, which the page measures and keeps in
    # a cookie (audit.html). 15 until it has.
    try:
        rows_per_page = max(5, min(100, int(request.COOKIES.get("audit_rows", 15))))
    except ValueError:
        rows_per_page = 15
    page = Paginator(rows, rows_per_page).get_page(request.GET.get("page"))
    actors, tables, actions = audit.facets()
    return _page(request, "datahealth/audit.html", tab="audit", page=page,
                 rows_per_page=rows_per_page, params=request.GET, actors=actors,
                 tables=[(t, TABLE_LABELS.get(t, t)) for t in tables],
                 actions=[(a, ACTION_LABELS.get(a, a.title())) for a in actions],
                 states=[(state, label) for state, (label, _) in audit.DB167_STATES.items()])


@admin_only
def audit_script(request):
    """Every change in the log, in order, as a T-SQL script for DB167."""
    with connection.cursor() as cur:
        script = db167_script.generate(cur)
    # The byte-order mark lets SQL Server Management Studio read it as UTF-8.
    response = HttpResponse("\ufeff" + script, content_type="application/sql; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{db167_script.filename()}"'
    return response


def _standing(entry):
    """Where each field of an entry stands with DB167, and what to say of the
    entry. A change holds a value DB167 has no column for (a sighting's
    depth_m) only on the website, whatever DB167 holds of the rest."""
    note = audit.DB167_STATES.get(entry["db167"], ("", ""))[1]
    fields = entry["db167_fields"]
    if not fields:
        return {}, note
    standing = {k: (state, audit.DB167_STATES[state][0]) for k, state in fields.items()}
    only_here = []
    for k in (entry["changes"] or {}):
        if k not in fields:
            mirror = k in db167_script.MIRRORS
            standing[k] = ("not_applicable", "Worked Out") if mirror else ("website", "Website Only")
            if not mirror:
                only_here.append(k)
    parts = []
    for state, text in (("applied", "DB167 holds"), ("pending", "DB167 does not hold yet"),
                        ("conflict", "DB167 holds something else for")):
        names = [audit_labels.field_label(k) for k, s in fields.items() if s == state]
        if names:
            parts.append(f"{text}: {', '.join(names)}.")
    if only_here:
        parts.append(f"DB167 has no column for {', '.join(audit_labels.field_label(k) for k in only_here)}, so only the website holds "
                     f"{'it' if len(only_here) == 1 else 'them'}.")
    return standing, " ".join(parts) if only_here or len(set(fields.values())) > 1 else note


@admin_only
def audit_entry(request, entry_id):
    """One change in full, with Undo."""
    if request.method == "POST" and not access.has(request.user, "edit_records"):
        raise PermissionDenied
    entry = audit.entry(entry_id)
    if entry is None:
        raise Http404("That entry is no longer in the log.")
    if request.method == "POST":
        try:
            gps_tracks.put_back(entry_id)
            events.record("audit", "undo", request=request, audit_id=entry_id, table=entry["target_table"],
                          record=str(entry["target_pk"]),
                          message=f"Undid {entry['action']} of {entry['target_table']} {entry['number']}.")
            messages.success(request, f"Undone: {TABLE_LABELS.get(entry['target_table'], entry['target_table'])} "
                                      f"{entry['number']} is back as it was, and the entry is gone from the log.")
            return redirect("admin_audit")
        except (LookupError, ValueError) as exc:
            messages.error(request, str(exc))
        except Exception as exc:
            messages.error(request, f"{type(exc).__name__}: {exc}")
        return redirect(request.path)
    numbers = _effort_numbers([entry["changes"]])
    row = _describe({"table": entry["target_table"], "pk": entry["target_pk"], "number": entry["number"],
                     "action": entry["action"], "changes": entry["changes"], "db167": entry["db167"]}, numbers)
    standing, row["db167_note"] = _standing(entry)
    changes = [(label, old, new, standing.get(name), name)
               for label, old, new, name in audit_labels.shown_changes(entry["changes"], numbers)]
    return _page(request, "datahealth/audit_entry.html", tab="audit", entry=entry, row=row,
                 changes=changes, blocked=audit.undoable({"action": entry["action"],
                                                          "restored_by": entry["restored_by"]}))


# The data pipeline's documentation


def _diff():
    """The diff, with signed counts formatted for the page."""
    tables = []
    for t in pipeline.DIFF:
        causes = [{**c, "rows_text": f"{c['rows']:+,}"} for c in t["causes"]]
        tables.append({**t, "causes": causes, "change_text": f"{t['new_rows'] - t['today_rows']:+,}"})
    return tables


def _entries():
    """Every dbo table's entry, in catalog order, with its rows attached."""
    fixes = {}
    for f in pipeline.FIXES:
        fixes.setdefault(f["table"], []).append(f)
    out = []
    with connection.cursor() as cur:
        tracks = pipeline.unmatched_tracks(cur)
    for e in pipeline.ENTRIES:
        name = e["table"]
        unlinked = tracks if name == "TrackT" else pipeline.UNLINKED.get(name, [])
        table_fixes = sorted(fixes.get(name, []), key=lambda f: (f["column"].lower(), -f["records"]))
        columns = pipeline.column_rows(name, table_fixes)
        changed = 0 if name == "VesselListT" else sum(1 for *_, changes in columns if changes)
        pk, _, legacy = pipeline.primary_key(name)
        about = e.get("about") or pipeline.ABOUT[name]
        out.append({
            **e, "about": about, "label": about.split(":")[0].split(",")[0].rstrip(".").split(". ")[0],
            "rows": pipeline.DB167_TABLES.get(name), "pk": pk, "new_id": bool(legacy),
            "columns": columns, "changed_columns": changed,
            "unlinked_rows": unlinked, "unlinked_count": sum(u["records"] for u in unlinked),
            "no_change": not (changed or legacy or unlinked or e.get("extra") or e.get("duplicates")),
        })
    return out


@admin_only
def data_pipeline(request):
    tables = pipeline.tables()
    entries = _entries()
    return render(request, "datahealth/pipeline.html", {
        "section": "cascadia-admin",
        "tab": "pipeline",
        "tables": tables,
        "total_rows": sum(t[1] for t in tables),
        "dbo_count": sum(1 for t in tables if t[2]),
        "views_help": pipeline.VIEWS_HELP,
        "db167_views": pipeline.DB167_VIEWS,
        "overview": pipeline.OVERVIEW,
        "step1": pipeline.STEP1,
        "step2": pipeline.STEP2,
        "step3": pipeline.STEP3,
        "rules": pipeline.RULES,
        "track_help": pipeline.TRACK_HELP,
        "diff_help": pipeline.DIFF_HELP,
        "entries": [e for e in entries if not e["no_change"]],
        "unchanged": [e for e in entries if e["no_change"]],
        "track_states": pipeline.TRACK_STATES,
        "app_views": pipeline.APP_VIEWS,
        "direct_reads": pipeline.DIRECT_READS,
        "schema_diff": pipeline.SCHEMA_DIFF,
        "diff": _diff(),
    })
