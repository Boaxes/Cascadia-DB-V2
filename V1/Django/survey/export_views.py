"""The Export Tool: the page, its live preview, the stack of queries, and the
download.

The page's address holds everything the reader chose (format, zone, which
sheets and columns), so removing a query or coming back to the page does not
lose it, and the preview and the download read the same parameters.
"""

import datetime
import tempfile

from django.contrib import messages
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from datahealth import access, events

from . import export_stack
from .export_sheets import (BY_KEY, PREVIEW_ROWS, SHEETS, Choice, Plan,
                            shape, track_file_count, track_files)
from .exporters import (DATE_FORMATS, FORMATS, ZIPPED, ZONES, format_value,
                        write_export)



def holds(fmt, sheet):
    """Whether a format can take a sheet."""
    kind = FORMATS[fmt]["holds"]
    if kind == "all":
        return True
    return bool(sheet.geometry) if kind == "positions" else sheet.key in kind


def _json_wanted(request):
    return request.headers.get("X-Requested-With") == "fetch"


def _page_url(request, query=""):
    url = reverse("export")
    return f"{url}?{query}" if query else url


def _next(request, default=None):
    """Where to go back to: a page on this site, never anywhere else."""
    target = request.POST.get("next") or ""
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                                  require_https=request.is_secure()):
        return target
    return default or _page_url(request)


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


@access.require("export_data")
def export_page(request):
    choice = Choice.from_params(request.GET)
    plan = Plan(export_stack.load(request))

    queries = []
    for number, (entry, counts) in enumerate(zip(plan.entries, plan.query_counts()), 1):
        problem = next((why for broken, why in plan.broken if broken is entry), None)
        related = export_stack.RELATED.get(entry["kind"])
        queries.append({"number": number, "label": entry["label"], "efforts": counts[0],
                        "sightings": counts[1], "problem": problem,
                        "related_label": export_stack.RELATED_LABELS.get(related),
                        "related": export_stack.brings_related(entry),
                        "note": "Sightings and the Efforts that match the same filters"
                                if entry["kind"] == "explore" else ""})

    sheets = []
    for sheet in SHEETS:
        wanted = choice.keys(sheet)
        groups = []
        for column in sheet.columns:
            if not groups or groups[-1]["name"] != column.group:
                groups.append({"name": column.group, "appended": column.appended, "columns": []})
            groups[-1]["columns"].append({"key": column.key, "label": column.label,
                                          "checked": column.key in wanted, "required": column.required})
        sheets.append({
            "key": sheet.key, "title": sheet.title, "layout": sheet.layout,
            "rows": sheet.count(plan), "ticked": sheet.key in choice.sheets,
            "chooser": sheet.chooser, "groups": groups,
            "chosen": len(wanted), "total": len(sheet.columns),
        })

    efforts = next(s["rows"] for s in sheets if s["key"] == "efforts")
    sightings = next(s["rows"] for s in sheets if s["key"] == "sightings")
    return render(request, "survey/export.html", {
        "section": "export",
        "queries": queries,
        "sheets": sheets,
        "choice": choice,
        "formats": [{"key": key, "label": f["label"], "note": f["note"], "zipped": key in ZIPPED,
                     "holds": ",".join(sh.key for sh in SHEETS if holds(key, sh))}
                    for key, f in FORMATS.items()],
        "zones": ZONES,
        "date_formats": list(DATE_FORMATS.items()),
        "raw": choice.raw,
        "track_files": track_file_count(plan),
        "efforts_in_all": efforts,
        "sightings_in_all": sightings,
        "ready": bool(plan.entries) and not plan.broken,
        "first_tab": next((s["key"] for s in sheets if s["ticked"]), ""),
        "preview_rows": PREVIEW_ROWS,
    })


@access.require("export_data")
def export_preview(request):
    """The first rows of one sheet, and its true row count, for the page."""
    sheet = BY_KEY.get(request.GET.get("preview"))
    if sheet is None:
        raise Http404("No such sheet.")
    choice = Choice.from_params(request.GET)
    plan = Plan(export_stack.load(request))
    out = shape(sheet, plan, choice, limit=PREVIEW_ROWS)
    rows = [[format_value(v, k, choice.date_format) for v, k in zip(values, out.kinds)]
            for values, _wkb, _meta in out.rows]
    return JsonResponse({
        "title": sheet.title,
        "total": sheet.count(plan),
        "columns": [{"label": h, "appended": a} for h, a in zip(out.headers, out.appended)],
        "rows": rows,
    })


# ---------------------------------------------------------------------------
# The stack
# ---------------------------------------------------------------------------


@access.require("export_data")
@require_POST
def export_add(request):
    kind = request.POST.get("kind")
    qs = f"id={request.POST.get('id', '')}" if kind in export_stack.ONE_RECORD else request.POST.get("qs", "")
    try:
        entry, added = export_stack.add(request, kind, qs, request.POST.get("related") != "0")
    except export_stack.ExportError as exc:
        if _json_wanted(request):
            return JsonResponse({"error": str(exc)}, status=400)
        messages.error(request, str(exc))
        return redirect(_next(request))

    if _json_wanted(request):
        return JsonResponse({"added": added, "count": export_stack.count(request), "label": entry["label"]})
    messages.success(request, f"Added to the export: {entry['label']}." if added
                     else f"Already in the export: {entry['label']}.")
    return redirect(_next(request))


@access.require("export_data")
@require_POST
def export_remove(request):
    index = request.POST.get("index", "")
    export_stack.remove(request, int(index) if index.isdigit() else -1)
    if _json_wanted(request):
        return JsonResponse({"count": export_stack.count(request)})
    return redirect(_next(request))


@access.require("export_data")
@require_POST
def export_related(request):
    """Turn a query's related records on or off."""
    index = request.POST.get("index", "")
    export_stack.set_related(request, int(index) if index.isdigit() else -1,
                             request.POST.get("related") == "1")
    if _json_wanted(request):
        return JsonResponse({"count": export_stack.count(request)})
    return redirect(_next(request))


# ---------------------------------------------------------------------------
# The download
# ---------------------------------------------------------------------------


def _refuse(request, message):
    """Back to the page with the reason, and everything chosen kept."""
    messages.error(request, message)
    return redirect(_page_url(request, request.GET.urlencode()))


@access.require("export_data")
def export_download(request):
    choice = Choice.from_params(request.GET)
    fmt = request.GET.get("format", choice.format)
    if fmt not in FORMATS:
        return _refuse(request, f"{fmt} is not a format this tool writes.")

    plan = Plan(export_stack.load(request))
    if not plan.entries:
        return _refuse(request, "Add a query to the export first. Use Add To Export on Explore, "
                                "Efforts, Sightings or a record's page.")
    if plan.broken:
        entry, why = plan.broken[0]
        return _refuse(request, f"{entry['label']} could not be read, so nothing was downloaded. "
                                f"Remove it and try again. {why}")

    ticked = [BY_KEY[key] for key in choice.sheets]
    chosen = [s for s in ticked if holds(fmt, s)]
    if not chosen:
        if not ticked:
            return _refuse(request, "Tick at least one sheet to download.")
        if fmt == "gpx":
            return _refuse(request, "GPX holds Efforts as tracks and Sightings as waypoints. "
                                    "Tick Efforts or Sightings.")
        return _refuse(request, f"{FORMATS[fmt]['label']} holds sheets that have positions: Efforts, "
                                "Sightings, Timeline and Weather. Tick one of them.")

    sheets = [shape(sheet, plan, choice) for sheet in chosen]
    zone = choice.zone.name
    note = f"Times are in {'UTC' if zone == 'UTC' else 'Pacific time'}."

    body = tempfile.TemporaryFile()
    try:
        write_export(fmt, sheets, body, choice.date_format, zone == "UTC", note,
                     track_files(plan) if choice.raw else None)
    except Exception as error:
        body.close()
        events.record("export", "failed", request=request, level="error",
                      message=f"A {fmt} export failed: {type(error).__name__}: {error}"[:500],
                      format=fmt, sheets=[s.key for s in chosen])
        raise
    size = body.seek(0, 2)
    body.seek(0)
    events.record("export", "download", request=request,
                  message=f"{FORMATS[fmt]['label']} export of {len(chosen)} sheet{'s' if len(chosen) != 1 else ''}.",
                  format=fmt, sheets=[s.key for s in chosen], queries=len(plan.entries),
                  raw_track_files=bool(choice.raw), zone=zone, size_bytes=size)

    name = f"cascadia_export_{datetime.date.today().isoformat()}_{zone.lower()}"
    if choice.raw and fmt not in ZIPPED:
        extension, content_type = "zip", "application/zip"
    else:
        extension, content_type = FORMATS[fmt]["extension"], FORMATS[fmt]["type"]
    response = FileResponse(body, as_attachment=True, filename=f"{name}.{extension}",
                            content_type=content_type)
    # Not worth compressing again: see GZipExceptDownloads.
    response.no_gzip = True
    return response
