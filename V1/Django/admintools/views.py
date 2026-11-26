"""The admin panel: a dashboard, the GPS track files and the audit log."""

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.db.models.functions import ExtractMonth, ExtractYear
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from survey import track_objects
from survey.filters import NON_ANIMAL, filter_efforts
from survey.models import DailyEffort, Sighting, Track
from survey.services import PAGE_SIZES, filter_options, paginate

from . import audit, trackfix
from .gps import tracks

# The admin login is the one with is_staff. Everybody else gets the survey site
# and nothing else.
admin_only = user_passes_test(lambda user: user.is_staff, login_url="/login/")

TABLE_LABELS = {"SightingT": "Sighting", "DailyEffortT": "Effort", "TrackT": "Track file",
                "DailyConditionT": "Weather reading", "DailyEventT": "Log entry",
                "SampleT": "Sample"}
ACTION_LABELS = {"update": "Edited", "associate": "Linked", "dissociate": "Unlinked",
                 "upload": "Uploaded", "create": "Created", "delete": "Deleted",
                 "restore": "Restored"}


def _page(request, template, **context):
    context.setdefault("section", "admin")
    return render(request, template, context)


# The dashboard


def _stats():
    """Everything the dashboard draws. Cached: the numbers move slowly."""
    stats = cache.get("admin:stats:v3")
    if stats is not None:
        return stats
    animals = Sighting.objects.exclude(species__category=NON_ANIMAL)
    years = list(animals.exclude(sighting_date=None).order_by()
                 .annotate(y=ExtractYear("sighting_date")).values("y").annotate(n=Count("id")).order_by("y").values_list("y", "n"))
    months = dict(DailyEffort.objects.exclude(effort_date=None).order_by()
                  .annotate(m=ExtractMonth("effort_date")).values("m")
                  .annotate(n=Count("id")).values_list("m", "n"))
    top = sorted((s for s in filter_options()["species"] if s["category"] != NON_ANIMAL),
                 key=lambda s: -s["count"])[:10]
    regions = list(animals.exclude(daily_effort__region=None).order_by()
                   .values("daily_effort__region").annotate(n=Count("id"))
                   .order_by("-n").values_list("daily_effort__region", "n")[:8])
    efforts = DailyEffort.objects.count()
    problems = trackfix.counts()
    # Efforts whose track file is in storage: the main site's "Available".
    with_track = DailyEffort.objects.filter(
        tracks__track_status__in=trackfix.HAS_FILE).distinct().count()
    span = [y for y, _ in years]
    stats = {
        "tiles": [
            {"label": "Sightings", "value": animals.count()},
            {"label": "Efforts", "value": efforts},
            {"label": "Species recorded", "value": sum(
                1 for s in filter_options()["species"]
                if s["count"] and s["category"] not in (NON_ANIMAL, "unidentified"))},
            {"label": "Years covered", "value": f"{span[0]}–{span[-1]}" if span else "–"},
        ],
        "coverage": {"with": with_track, "total": efforts,
                     "percent": round(100 * with_track / efforts) if efforts else 0},
        "problems": problems,
        "charts": {
            "years": {"title": "Sightings per year", "unit": "sightings",
                      "labels": [str(y) for y, _ in years], "values": [n for _, n in years]},
            "months": {"title": "Efforts by month, all years", "unit": "efforts",
                       "labels": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
                       "values": [months.get(m, 0) for m in range(1, 13)]},
            "species": {"title": "Most recorded species", "unit": "sightings",
                        "labels": [s["label"] for s in top], "values": [s["count"] for s in top],
                        "dots": [s["colour"] for s in top]},
            "regions": {"title": "Sightings by region", "unit": "sightings",
                        "labels": [r for r, _ in regions], "values": [n for _, n in regions]},
        },
    }
    for tile in stats["tiles"]:
        if isinstance(tile["value"], int):
            tile["value"] = f"{tile['value']:,}"
    cache.set("admin:stats:v3", stats, 60 * 30)
    return stats


@admin_only
def dashboard(request):
    stats = _stats()
    rows, _total = audit.entries(limit=5)
    for row in rows:
        _describe(row)
    counts = stats["problems"]
    return _page(request, "admintools/dashboard.html", tab="dashboard", stats=stats,
                 recent=rows,
                 problems=[(k, v[0], counts[k]) for k, v in trackfix.PROBLEMS.items()])


# Track files


# The statuses an effort can have, which the Efforts page's own Vessel and
# Time filters apply to. Unlinked and lost files belong to no effort and have
# no vessel, so for those the page offers a file name search instead.
EFFORT_PROBLEMS = ("no_track", "missing_file")


def _problem_rows(problem, params):
    """The efforts or files with one problem, newest first."""
    q = (params.get("q") or "").strip()
    rows, applied = [], []
    if problem in EFFORT_PROBLEMS:
        efforts, applied, _excluded = filter_efforts(DailyEffort.objects.all(), params)
        if q:
            efforts = efforts.filter(Q(legacy_daily_effort_id=int(q)) if q.isdigit()
                                     else Q(locality__icontains=q))
            applied.append(f'matching "{q}"')
    if problem == "no_track":
        found = trackfix.efforts_without_track().filter(pk__in=efforts.values("pk"))
        for e in found.select_related("vessel"):
            rows.append({"date": e.effort_date, "vessel": e.vessel, "effort": e,
                         "locality": e.locality, "file": None,
                         "url": f"/admin/tracks/effort/{e.legacy_daily_effort_id}/"})
    else:
        found = trackfix.tracks_with(problem).select_related("daily_effort", "vessel")
        if problem == "missing_file":
            found = found.filter(daily_effort__in=efforts.values("pk"))
        elif q:
            found = found.filter(object_key__icontains=q)
            applied.append(f'with "{q}" in the file name')
        for t in found:
            e = t.daily_effort
            rows.append({"date": t.survey_date, "vessel": t.vessel, "effort": e,
                         "locality": e.locality if e else None, "file": t.object_key,
                         "points": t.point_count,
                         "url": (f"/admin/tracks/effort/{e.legacy_daily_effort_id}/" if e
                                 else f"/admin/tracks/file/{t.legacy_track_id}/")})

    # Potential matches: for an effort, unlinked files that day; for a file,
    # efforts that day. Counted in one query, not one per row.
    dates = {r["date"] for r in rows if r["date"]}
    if problem in EFFORT_PROBLEMS:
        pool = (trackfix.tracks_with("unlinked").filter(survey_date__in=dates).order_by()
                .values_list("survey_date").annotate(n=Count("id")))
    else:
        pool = (DailyEffort.objects.filter(effort_date__in=dates).order_by()
                .values_list("effort_date").annotate(n=Count("id")))
    by_day = dict(pool)
    for r in rows:
        r["matches"] = by_day.get(r["date"], 0)
    # Newest first; a record with no date last.
    rows.sort(key=lambda r: (r["date"] is not None, r["date"] or 0), reverse=True)
    return rows, applied


@admin_only
def tracks(request):
    problem = request.GET.get("problem") or "no_track"
    if problem not in trackfix.PROBLEMS:
        problem = "no_track"
    rows, applied = _problem_rows(problem, request.GET)
    page, per_page = paginate(request, rows)
    counts = trackfix.counts()
    return _page(request, "admintools/tracks.html", tab="tracks", page=page,
                 per_page=per_page, page_sizes=PAGE_SIZES, problem=problem,
                 for_efforts=problem in EFFORT_PROBLEMS, applied=applied,
                 problems=[(k, v[0], v[1], counts[k]) for k, v in trackfix.PROBLEMS.items()],
                 note=trackfix.PROBLEMS[problem][1],
                 options=filter_options(), params=request.GET,
                 selected={"vessels": request.GET.getlist("vessel"),
                           "months": request.GET.getlist("month"),
                           "years": request.GET.getlist("year")},
                 storage_ok=track_objects.can_write())


def _act(request, fix):
    """Run one fix, turning its answer into a message on the page."""
    try:
        messages.success(request, fix())
        return True
    except ValueError as exc:
        messages.error(request, str(exc))
    except Exception as exc:
        messages.error(request, f"{type(exc).__name__}: {exc}")
    return False


@admin_only
def track_effort(request, legacy_id):
    """Everything to do with one effort's track file, in one place."""
    effort = get_object_or_404(DailyEffort.objects.select_related("vessel"),
                               legacy_daily_effort_id=legacy_id)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "link":
            track = get_object_or_404(Track, legacy_track_id=request.POST.get("track"))
            _act(request, lambda: trackfix.link(request.user, track, effort))
        elif action == "unlink":
            track = get_object_or_404(Track, legacy_track_id=request.POST.get("track"))
            _act(request, lambda: trackfix.unlink(request.user, track))
        elif action == "upload":
            upload = request.FILES.get("file")
            track_id = request.POST.get("track")
            if not upload:
                messages.error(request, "Choose a file first.")
            elif track_id:
                track = get_object_or_404(Track, legacy_track_id=track_id)
                _act(request, lambda: tracks.add(request.user, upload, track=track))
            else:
                _act(request, lambda: tracks.add(request.user, upload, effort=effort))
        return redirect(request.path)

    own = list(effort.tracks.select_related("vessel").order_by("object_key"))
    for t in own:
        t.problem = trackfix.problem_of(t)
    missing = [t for t in own if t.problem == "missing_file"]
    return _page(request, "admintools/track_effort.html", tab="tracks", effort=effort,
                 own=own, missing=missing, matches=trackfix.files_on(effort.effort_date),
                 problem=("no_track" if not own else "missing_file" if missing else None),
                 labels=trackfix.PROBLEMS, storage_ok=track_objects.can_write())


@admin_only
def track_file(request, legacy_id):
    """One file: which effort it belongs to, or the file a record is missing."""
    track = get_object_or_404(Track.objects.select_related("daily_effort", "vessel"),
                              legacy_track_id=legacy_id)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "link":
            number = (request.POST.get("effort") or "").strip()
            effort = DailyEffort.objects.filter(legacy_daily_effort_id=number).first() \
                if number.isdigit() else None
            if effort is None:
                messages.error(request, f"There is no effort {number or 'with that number'}.")
            else:
                _act(request, lambda: trackfix.link(request.user, track, effort))
        elif action == "unlink":
            _act(request, lambda: trackfix.unlink(request.user, track))
        elif action == "upload":
            upload = request.FILES.get("file")
            if not upload:
                messages.error(request, "Choose a file first.")
            else:
                _act(request, lambda: tracks.add(request.user, upload, track=track))
        return redirect(request.path)

    track.problem = trackfix.problem_of(track)
    return _page(request, "admintools/track_file.html", tab="tracks", track=track,
                 matches=trackfix.efforts_on(track.survey_date, exclude=track.daily_effort_id),
                 labels=trackfix.PROBLEMS, storage_ok=track_objects.can_write())


# The audit log


def _describe(row):
    """Plain-English labels and a one-line summary of what changed."""
    row["table_label"] = TABLE_LABELS.get(row["table"], row["table"])
    row["action_label"] = ACTION_LABELS.get(row["action"], row["action"].title())
    fields = [(k, v) for k, v in (row.get("changes") or {}).items() if k not in ("geom",)]
    row["summary"] = "; ".join(
        f"{k}: {_short(v.get('old'))} → {_short(v.get('new'))}" for k, v in fields[:3]
    ) + ("…" if len(fields) > 3 else "")
    row["link"] = {"SightingT": f"/sightings/{row['pk']}/", "DailyEffortT": f"/efforts/{row['pk']}/",
                   "TrackT": f"/admin/tracks/file/{row['pk']}/"}.get(row["table"])
    return row


def _short(value):
    if value is None or value == "":
        return "empty"
    text = str(value)
    return text if len(text) <= 40 else text[:37] + "…"


@admin_only
def audit_log(request):
    """Who changed what, when, and why. The import's corrections only on request."""
    legacy = request.GET.get("legacy") == "1"
    rows, total = audit.entries(
        limit=100000, actor=request.GET.get("actor") or None,
        table=request.GET.get("table") or None, action=request.GET.get("action") or None,
        legacy=legacy, target=(request.GET.get("q") or "").strip() or None)
    for row in rows:
        _describe(row)
    # As many changes as fit the window, which the page measures and keeps in
    # a cookie (audit.html). 15 until it has.
    try:
        rows_per_page = max(5, min(100, int(request.COOKIES.get("audit_rows", 15))))
    except ValueError:
        rows_per_page = 15
    page = Paginator(rows, rows_per_page).get_page(request.GET.get("page"))
    actors, tables, actions = audit.facets()
    return _page(request, "admintools/audit.html", tab="audit", page=page,
                 rows_per_page=rows_per_page, params=request.GET, legacy=legacy,
                 actors=[a for a in actors if legacy or a != audit.LEGACY_ACTOR],
                 tables=[(t, TABLE_LABELS.get(t, t)) for t in tables],
                 actions=[(a, ACTION_LABELS.get(a, a.title())) for a in actions])


@admin_only
def audit_entry(request, entry_id):
    """One change in full, with Undo."""
    entry = audit.entry(entry_id)
    if entry is None:
        raise Http404("That entry is no longer in the log.")
    if request.method == "POST":
        try:
            uploaded = audit.undo(entry_id)
            if uploaded:
                track_objects.delete(uploaded)
            messages.success(request, f"Undone: {TABLE_LABELS.get(entry['target_table'], entry['target_table'])} "
                                      f"{entry['target_pk']} is back as it was, and the entry is gone from the log.")
            return redirect("admin_audit")
        except (LookupError, ValueError) as exc:
            messages.error(request, str(exc))
        except Exception as exc:
            messages.error(request, f"{type(exc).__name__}: {exc}")
        return redirect(request.path)
    row = _describe({"table": entry["target_table"], "pk": entry["target_pk"],
                     "action": entry["action"], "changes": entry["changes"]})
    changes = [(k, v.get("old"), v.get("new")) for k, v in (entry["changes"] or {}).items()]
    return _page(request, "admintools/audit_entry.html", tab="audit", entry=entry, row=row,
                 changes=changes, blocked=audit.undoable({"action": entry["action"],
                                                          "restored_by": entry["restored_by"]}))
