"""The Track File Manager: one workspace page, two pop-ups, and the JSON the
page and the pop-ups talk to.

Everything here is for people holding access_data_health. The explorer asks for
its files a page at a time, filtered on the server, because there are more than
1,500 of them. Every change goes through gps/tracks.py or trackfix.py, which
write the audit log, so nothing here changes data on its own.
"""

import json
import re

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from survey import track_checks, track_objects
from survey.models import DailyEffort, Track

from . import access, audit, trackfix
from .gps import tracks as gps

admin_only = access.require("access_data_health")

PAGE = 100
HEADER = "datetime_utc,latitude,longitude\n"

# What the History panel calls each change.
HISTORY_LABELS = {
    "create": "File Imported", "upload": "File Uploaded", "edit_file": "Saved",
    "associate": "Matched To An Effort", "dissociate": "Match Removed",
    "update": "Edited", "delete": "Deleted", "restore": "Restored",
}


def _fail(message, status=400, **more):
    return JsonResponse({"ok": False, "message": message, **more}, status=status)


def _track(track_id):
    return get_object_or_404(Track.objects.select_related("daily_effort__vessel", "vessel"),
                             legacy_track_id=track_id)


def _stored(track):
    """The file's text, or the blank header when storage has none."""
    body = track_objects.get(track.object_key) if track.object_key else None
    return body.decode("utf-8-sig", errors="replace") if body is not None else HEADER


def _history(track):
    """The changes to one track, newest first, each with the earlier version
    it kept if it saved the file. Versions in storage no entry names (after an
    undo) are listed last."""
    rows, named = [], set()
    for e in audit.for_record("TrackT", track.legacy_track_id):
        version = (e["changes"].get("version") or {}).get("new")
        if version:
            named.add(version)
        what, note = HISTORY_LABELS.get(e["action"], e["action"]), e["comment"]
        if e["action"] == "edit_file":
            points = (e["changes"].get("point_count") or {}).get("new")
            what = "Filled From File" if (e["comment"] or "").startswith("Filled ") else "Saved"
            note = f"{points:,} points" if points is not None else None
        rows.append({"id": e["id"], "at": e["at"].isoformat(), "who": e["actor"],
                     "what": what, "note": note, "version": version})
    if track.object_key:
        for kept in reversed(track_objects.under(track_objects.VERSIONS + track.object_key)):
            if kept not in named:
                made = re.match(r"(\d{4})(\d\d)(\d\d)T(\d\d)(\d\d)(\d\d)Z", kept.rsplit("/", 1)[-1])
                rows.append({"id": None, "who": None, "what": "Earlier Version", "note": None, "version": kept,
                             "at": "{}-{}-{}T{}:{}:{}".format(*made.groups()) if made else None})
    return rows


def _effort(track):
    return _effort_info(track.daily_effort)


def _effort_info(e):
    if e is None:
        return None
    return {"id": e.legacy_daily_effort_id, "date": e.effort_date.isoformat() if e.effort_date else None,
            "vessel": e.vessel.code if e.vessel else None, "locality": e.locality,
            "group": e.research_group, "url": f"/efforts/{e.legacy_daily_effort_id}/"}


def _describe(track):
    """Everything the workspace needs to open one file."""
    day = track.survey_date
    if day is None and track.start_time_utc:
        day = gps.pacific_date(track.start_time_utc.strftime("%Y-%m-%d %H:%M:%S"))
    shared = (Track.objects.filter(object_key__iexact=track.object_key)
              .exclude(pk=track.pk).values_list("legacy_track_id", flat=True)) if track.object_key else []
    return {
        "id": track.legacy_track_id, "name": track.object_key,
        "date": day.isoformat() if day else None,
        "vessel": track.vessel.code if track.vessel else None, "group": track.research_group,
        "state": trackfix.state_of(track), "blank": not track.point_count,
        "text": _stored(track), "effort": _effort(track),
        "efforts": trackfix.efforts_on(day, track.research_group),
        "history": _history(track), "shared": list(shared),
        "checks": track_checks.read(track.object_key) if track.object_key else None,
        "timeline": trackfix.timeline_events(track.daily_effort),
    }


def _deleted(track_id):
    """The newest delete entry for a TrackID that is no longer there."""
    for entry in audit.deleted("TrackT"):
        if entry["pk"] == str(track_id):
            return entry
    return None


def _describe_deleted(entry):
    row = (entry["snapshot"].get("TrackT") or [{}])[0]
    moved = (entry["snapshot"].get("storage") or {}).get("restore_deleted")
    body = track_objects.get(moved["from"]) if moved else None
    return {"id": int(entry["pk"]), "name": row.get("file_name") or row.get("TrackFileName"),
            "date": row.get("SurveyDate"), "vessel": row.get("Vessel"), "group": row.get("Research Group"),
            "state": "deleted", "blank": False, "effort": None, "efforts": [], "history": [],
            "shared": [],
            "text": body.decode("utf-8-sig", errors="replace") if body is not None else HEADER,
            "deleted": {"entry": entry["id"], "who": entry["actor"], "at": entry["at"].isoformat()}}


# The pages


@admin_only
def workspace(request):
    vessels, years = trackfix.facets()
    return render(request, "datahealth/tracks.html", {
        "section": "cascadia-admin", "tab": "tracks", "vessels": vessels, "years": years,
        "problems": track_checks.PROBLEMS,
        "storage_ok": track_objects.can_write(),
        "open": request.GET.get("open", ""), "import_effort": request.GET.get("import_effort", ""),
        "positions_effort": request.GET.get("positions_effort", "")})


@admin_only
def import_page(request):
    """The Import Files pop-up. With ?effort=<id>, that Effort is preselected."""
    number = request.GET.get("effort", "")
    effort = DailyEffort.objects.filter(legacy_daily_effort_id=number).select_related("vessel").first() \
        if number.isdigit() else None
    return render(request, "datahealth/track_import.html", {
        "section": "cascadia-admin", "tab": "tracks", "effort": effort,
        "storage_ok": track_objects.can_write()})


@admin_only
def fill_page(request, track_id):
    track = _track(track_id)
    return render(request, "datahealth/track_fill.html", {
        "section": "cascadia-admin", "tab": "tracks", "track": track,
        "storage_ok": track_objects.can_write()})


def _whole(value):
    """A whole number from text, or None: only the digits 0 to 9, and small enough for an ID
    column, so nothing a person types or edits into an address can reach the database as
    anything else."""
    value = str(value or "").strip()
    return int(value) if value.isascii() and value.isdigit() and len(value) <= 9 else None


def _effort_numbered(number):
    """The Effort with this Legacy ID, or None."""
    number = _whole(number)
    return DailyEffort.objects.filter(legacy_daily_effort_id=number).select_related("vessel").first() \
        if number is not None else None


@admin_only
def change_page(request):
    """The Change Track File pop-up on an Effort's page, and what it posts.
    ?effort=<number> is the Effort, and ?track=<id> the file it has now (none
    when the Effort has no file, and one is being chosen for it). Confirming
    swaps the files and lands back on the Effort."""
    source = request.POST if request.method == "POST" else request.GET
    effort = _effort_numbered(source.get("effort"))
    if effort is None:
        raise Http404("There is no such Effort.")
    old = None
    if source.get("track"):
        if _whole(source["track"]) is None:
            raise Http404("There is no such track file.")
        old = Track.objects.filter(legacy_track_id=_whole(source["track"]), daily_effort=effort).first()
        if old is None:
            messages.error(request, "That track file is no longer matched to this Effort.")
            return redirect(f"/efforts/{effort.legacy_daily_effort_id}/")
    if request.method == "POST":
        new = Track.objects.filter(legacy_track_id=_whole(request.POST.get("new")) or 0).first()
        try:
            if new is None:
                raise ValueError("Choose a track file first.")
            messages.success(request, trackfix.change(request.user, effort, new, old))
            return redirect(f"/efforts/{effort.legacy_daily_effort_id}/")
        except (ValueError, LookupError, RuntimeError) as exc:
            messages.error(request, str(exc))     # shown in the pop-up, which stays open
    return render(request, "datahealth/track_change.html", {
        "section": "cascadia-admin", "tab": "tracks", "effort": effort, "old": old})


@admin_only
@require_POST
def delete_page(request, track_id):
    """Delete from an Effort's page: the same delete, then back to the Effort."""
    track = _track(track_id)
    effort = track.daily_effort
    try:
        messages.success(request, gps.remove(request.user, track))
    except (ValueError, LookupError, RuntimeError) as exc:
        messages.error(request, str(exc))
    return redirect(f"/efforts/{effort.legacy_daily_effort_id}/" if effort else "admin_tracks")


# The JSON


@admin_only
@require_GET
def api_files(request):
    status = request.GET.get("status")
    if status == "deleted":
        rows = trackfix.deleted_files(request.GET)
        return JsonResponse({"files": rows, "total": len(rows), "all": Track.objects.count()})
    try:
        offset = max(0, int(request.GET.get("offset", 0)))
    except ValueError:
        offset = 0
    rows, total = trackfix.files(request.GET, offset, PAGE)
    return JsonResponse({"files": rows, "total": total, "all": Track.objects.count(),
                         "offset": offset})


@admin_only
@require_GET
def api_positions(request):
    """The explorer's From Positions list: Efforts with no track file and at least
    two recorded positions, searched and capped on the server."""
    rows, total = trackfix.position_efforts(request.GET)
    return JsonResponse({"files": rows, "total": total, "cap": trackfix.POSITIONS_CAP})


@admin_only
@require_GET
def api_positions_draft(request, effort_id):
    """One Effort's recorded positions as an unsaved file, for the editor."""
    effort = _effort_numbered(effort_id)
    if effort is None:
        return _fail("There is no such Effort.", status=404)
    try:
        trackfix.check_room(effort)
        name = gps.positions_key(effort) if effort.effort_date else None
    except ValueError as exc:
        return _fail(str(exc), status=409)
    rows = trackfix.position_rows(effort)
    if name is None or len(rows) < 2:
        return _fail("This Effort has no date, or fewer than two recorded positions, so there is "
                     "nothing to make a track from.", status=404)
    return JsonResponse({
        "ok": True, "id": None, "name": name, "date": effort.effort_date.isoformat(),
        "vessel": effort.vessel.code if effort.vessel else None, "group": effort.research_group,
        "state": "draft", "blank": False, "draft": True, "text": gps.positions_text(rows),
        "effort": _effort_info(effort), "efforts": [], "history": [], "shared": [],
        "timeline": trackfix.timeline_events(effort)})


@admin_only
@require_POST
def api_positions_save(request, effort_id):
    """Save an Effort's draft as its track file. Everything is checked again here:
    the person, that the Effort still has no track, and the text itself."""
    effort = _effort_numbered(effort_id)
    if effort is None:
        return _fail("There is no such Effort.", status=404)
    try:
        track_id, message = gps.add_text(request.user, request.POST.get("text", ""), effort)
    except gps.LineErrors as exc:
        return _fail(str(exc), errors=exc.errors)
    except (ValueError, RuntimeError) as exc:
        return _fail(str(exc))
    return JsonResponse({"ok": True, "message": message, "id": track_id})


@admin_only
@require_GET
def api_candidates(request):
    """The files the Change Track File pop-up offers an Effort."""
    effort = _effort_numbered(request.GET.get("effort"))
    if effort is None:
        return _fail("There is no such Effort.", status=404)
    rows, total = trackfix.candidates(effort, request.GET.get("q"), request.GET.get("all_dates") == "1")
    return JsonResponse({"ok": True, "files": rows, "total": total})


@admin_only
@require_GET
def api_open(request, track_id):
    track = Track.objects.filter(legacy_track_id=track_id).select_related(
        "daily_effort__vessel", "vessel").first()
    if track is None:
        entry = _deleted(track_id)
        if entry is None:
            raise Http404("There is no such track file.")
        return JsonResponse(_describe_deleted(entry))
    return JsonResponse(_describe(track))


@admin_only
@require_POST
def api_save(request, track_id):
    track = _track(track_id)
    try:
        message = gps.save_text(request.user, track, request.POST.get("text", ""))
    except gps.LineErrors as exc:
        return _fail(str(exc), errors=exc.errors)
    except (ValueError, LookupError, RuntimeError) as exc:
        return _fail(str(exc))
    return JsonResponse({"ok": True, "message": message, **_after(track.legacy_track_id)})


def _after(track_id):
    """What changed on the page after a change: the state, the Effort, the
    History and whether the file is stored."""
    track = _track(track_id)
    now = _describe(track)
    return {key: now[key] for key in ("state", "blank", "effort", "efforts", "history", "text", "checks", "timeline")}


@admin_only
@require_POST
def api_fill_preview(request, track_id):
    track = _track(track_id)
    upload = request.FILES.get("file")
    if not upload:
        return _fail("Choose a file first.")
    try:
        gps.check_size(upload.name, upload.size)
        return JsonResponse({"ok": True, **gps.fill_preview(track, upload)})
    except (ValueError, RuntimeError) as exc:
        return _fail(str(exc))


@admin_only
@require_POST
def api_fill(request, track_id):
    track = _track(track_id)
    upload = request.FILES.get("file")
    if not upload:
        return _fail("Choose a file first.")
    try:
        gps.check_size(upload.name, upload.size)
        message = gps.fill(request.user, track, upload)
    except gps.LineErrors as exc:
        return _fail(str(exc), errors=exc.errors)
    except (ValueError, LookupError, RuntimeError) as exc:
        return _fail(str(exc))
    return JsonResponse({"ok": True, "message": message, **_after(track.legacy_track_id)})


@admin_only
@require_GET
def api_version(request, track_id):
    """The text of one earlier version, for the editor to load."""
    track = _track(track_id)
    key = request.GET.get("key", "")
    if (not track.object_key or ".." in key.split("/")
            or not key.startswith(f"{track_objects.VERSIONS}{track.object_key}/")):
        raise Http404("That is not a version of this file.")
    body = track_objects.get(key)
    if body is None:
        raise Http404("That version is no longer in storage.")
    return JsonResponse({"ok": True, "text": body.decode("utf-8-sig", errors="replace")})


@admin_only
@require_POST
def api_match(request, track_id):
    track = _track(track_id)
    number = (request.POST.get("effort") or "").strip()
    effort = DailyEffort.objects.filter(legacy_daily_effort_id=number).select_related("vessel").first() \
        if number.isdigit() else None
    if effort is None:
        return _fail(f"There is no Effort {number or 'with that number'}.")
    try:
        message = trackfix.link(request.user, track, effort)
    except ValueError as exc:
        return _fail(str(exc))
    return JsonResponse({"ok": True, "message": message, **_after(track_id)})


@admin_only
@require_POST
def api_unmatch(request, track_id):
    track = _track(track_id)
    try:
        message = trackfix.unlink(request.user, track)
    except ValueError as exc:
        return _fail(str(exc))
    return JsonResponse({"ok": True, "message": message, **_after(track_id)})


@admin_only
@require_POST
def api_delete(request, track_id):
    track = _track(track_id)
    try:
        message = gps.remove(request.user, track)
    except (ValueError, LookupError, RuntimeError) as exc:
        return _fail(str(exc))
    return JsonResponse({"ok": True, "message": message})


@admin_only
@require_POST
def api_restore(request, track_id):
    """Bring a deleted track, and its file, back."""
    entry = _deleted(track_id)
    if entry is None:
        return _fail("That track file was not deleted, or has been restored already.")
    try:
        gps.put_back(entry["id"], request.user)
    except (ValueError, LookupError) as exc:
        return _fail(str(exc))
    return JsonResponse({"ok": True, "message": "Restored. The file and its Effort match are back."})


@admin_only
@require_POST
def api_import_preview(request):
    """Import Files, step one: what each file is, and the Effort it probably
    belongs to. Nothing is stored."""
    found = []
    uploads = request.FILES.getlist("files")
    try:
        gps.check_batch(uploads)
    except ValueError as exc:
        return _fail(str(exc))
    for upload in uploads:
        try:
            info = gps.preview_upload(upload)
        except (ValueError, RuntimeError) as exc:
            found.append({"name": upload.name, "error": str(exc)})
            continue
        day = info["date"]
        info["efforts"] = trackfix.efforts_on(day)
        info["best"] = trackfix.suggest(day, info["vessel"])
        info["error"] = None if info["points"] else "That file has no usable GPS rows in it."
        found.append(info)
    return JsonResponse({"ok": True, "files": found})


@admin_only
@require_POST
def api_import(request):
    """Import Files, step two: each file with the person's choice for it, an
    Effort's number, or nothing to import it unmatched. A file they skipped is
    not sent."""
    try:
        choices = json.loads(request.POST.get("choices") or "{}")
    except ValueError:
        return _fail("The choices could not be read.")
    done = []
    uploads = request.FILES.getlist("files")
    try:
        gps.check_batch(uploads)
    except ValueError as exc:
        return _fail(str(exc))
    for upload in uploads:
        number = str(choices.get(upload.name) or "")
        try:
            effort = None
            if number:
                effort = DailyEffort.objects.filter(legacy_daily_effort_id=number) \
                    .select_related("vessel").first() if number.isdigit() else None
                if effort is None:
                    raise ValueError(f"There is no Effort {number}.")
            track_id, message = gps.add_file(request.user, upload, effort=effort)
            done.append({"name": upload.name, "ok": True, "message": message, "id": track_id})
        except (ValueError, RuntimeError) as exc:
            done.append({"name": upload.name, "ok": False, "message": str(exc)})
    return JsonResponse({"ok": all(d["ok"] for d in done), "done": done})
