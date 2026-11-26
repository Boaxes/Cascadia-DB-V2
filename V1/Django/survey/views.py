"""Every page the survey site serves.

Each view assembles what its template needs, so no template can trigger a
query. Filtering lives in filters.py because Explore, Efforts and Sightings
all have to filter the same way, and the export has to match the list it came
from.
"""

import datetime
import io
import json
import os
import zipfile

from django.contrib.auth.decorators import login_required
from django.contrib.gis.db.models import GeometryField
from django.contrib.gis.db.models.functions import AsGeoJSON
from django.core.cache import cache
from django.db.models import Count, Func, Q
from django.db import connection
from django.http import (Http404, HttpResponse, HttpResponseBadRequest,
                         JsonResponse, QueryDict)
from django.shortcuts import render

from .exporters import (OPTIONAL_SIGHTING_FIELDS, columns_for, csv_response,
                        excel_response, geojson_response)
from .filters import (NON_ANIMAL, filter_efforts, filter_sightings,
                      species_choices)
from . import track_objects
from .history import record_history
from .models import (DailyCondition, DailyEffort, DailyEvent,
                     Sighting, Species, Track)
from .services import (PAGE_SIZES, apply_sort, colour_profile, filter_options,
                       paginate)

# Explore, Efforts and Sightings each remember what they are showing, so
# filtering one list does not change what an export from another produces.
# Sorting and paging are left out: they describe a page, not a result.
EXPORT_AREAS = ("explore", "efforts", "sightings")
NOT_A_FILTER = {"page", "per_page", "sort",
                # How the page was left, kept in the link (filters.js): which
                # filter sections were open, and the Explore map's view and
                # layers. They describe the page, not the result.
                "open", "view", "base", "labels", "tracks", "points",
                "clusters"}


def remember_export_state(request, area, params, count):
    # Sessions are database rows, so writing one on every list page view is a
    # write to the database on every list page view. Only save when something
    # changed.
    state = request.session.get("export_state") or {}
    entry = {
        # Every value, not just the last: species, vessel and month repeat.
        "filters": {k: [v for v in params.getlist(k) if v] for k in params
                    if k not in NOT_A_FILTER and any(params.getlist(k))},
        "count": count,
    }
    if state.get(area) == entry:
        return
    state[area] = entry
    request.session["export_state"] = state


def export_state(request):
    stored = request.session.get("export_state") or {}
    return {area: stored.get(area) or {"filters": {}, "count": None}
            for area in EXPORT_AREAS}


# The Explore map

@login_required
def explore(request):
    error = None
    try:
        sightings, applied, excluded = filter_sightings(
            Sighting.objects.all(), request.GET
        )
        sighting_count = sightings.count()
        efforts, _applied, _excluded = filter_efforts(
            DailyEffort.objects.all(), request.GET
        )
        effort_count = efforts.count()
    except ValueError as exc:
        error, applied, excluded = str(exc), [], 0
        sighting_count = effort_count = 0

    # See the note in views/efforts.py.
    if not error:
        remember_export_state(request, "explore", request.GET, sighting_count)

    include_non_animal = request.GET.get("include_non_animal") == "1"

    return render(request, "survey/explore.html", {
        "section": "explore",
        "options": filter_options(),
        "species_list": species_choices(include_non_animal),
        "include_non_animal": include_non_animal,
        "species_meta": species_meta(colour_profile(request)),
        "legend": legend_entries(),
        "sighting_count": sighting_count,
        "effort_count": effort_count,
        "applied": applied,
        "excluded_no_position": excluded,
        "error": error,
        "params": request.GET,
        # Species and vessel take several values, so the template needs every
        # one of them to mark the right options selected, not just the last.
        "selected": {
            "species": request.GET.getlist("species"),
            "vessels": request.GET.getlist("vessel"),
            "months": request.GET.getlist("month"),
            "years": request.GET.getlist("year"),
        },
    })


def species_meta(profile):
    """Name and colour for every species, keyed by id.

    The sightings payload carries only a species id per row, so the browser
    needs this to label a popup or colour a dot. It is small enough to embed
    in the page and saves a third request. The colours are the ones the
    filter tags use, in the chosen profile.
    """
    key = "colour" if profile == "generic" else "cascadia_colour"
    return {
        str(s["id"]): {"name": s["label"], "colour": s[key]}
        for s in filter_options()["species"]
    }


def legend_entries():
    """One row per animal group that has sightings, in the picker's order."""
    return [g for g in filter_options()["species_groups"]
            if g["count"] and g["key"] != "other"]


# Efforts

EFFORT_SORTS = {
    "date": "effort_date",
    "id": "legacy_daily_effort_id",
    "research_group": "research_group",
    "vessel": "vessel__code",
    "locality": "locality",
    "region": "region",
    "survey_type": "survey_type",
    "distance": "distance_recorded_nm",
    "sightings": "sighting_count",
}


@login_required
def effort_list(request):
    # One query for the page of rows. The two counts are annotated rather
    # than looked up per row, which would be 1 + 2N queries.
    queryset = (
        DailyEffort.objects.select_related("vessel")
        .annotate(
            sighting_count=Count("sightings", distinct=True),
            track_count=Count("tracks", distinct=True),
            available_tracks=Count(
                "tracks",
                filter=Q(tracks__track_status__in=Track.HAS_FILE),
                distinct=True,
            ),
        )
    )

    error = None
    try:
        queryset, applied, excluded = filter_efforts(queryset, request.GET)
    except ValueError as exc:
        error, applied, excluded = str(exc), [], 0

    queryset, sort_key, sort_desc = apply_sort(queryset, request, EFFORT_SORTS, "-date")
    page, per_page = paginate(request, queryset)

    # Only a filter set that actually worked is worth remembering. Storing
    # one that could not be read would hand the export a query it cannot run.
    if not error:
        remember_export_state(request, "efforts", request.GET, page.paginator.count)

    return render(request, "survey/effort_list.html", {
        "section": "efforts",
        "page": page,
        "per_page": per_page,
        "page_sizes": PAGE_SIZES,
        "sort_key": sort_key,
        "sort_desc": sort_desc,
        "applied": applied,
        "excluded_no_position": excluded,
        "error": error,
        "options": filter_options(),
        "params": request.GET,
        "selected": {
            "species": request.GET.getlist("species"),
            "vessels": request.GET.getlist("vessel"),
            "months": request.GET.getlist("month"),
            "years": request.GET.getlist("year"),
        },
    })


@login_required
def effort_detail(request, legacy_id):
    """One effort: what it was, its tracks, its timeline and its sightings."""
    try:
        effort = DailyEffort.objects.select_related("vessel").get(
            legacy_daily_effort_id=legacy_id
        )
    except DailyEffort.DoesNotExist:
        raise Http404(f"No effort with identifier {legacy_id}")

    tracks = list(effort.tracks.select_related("vessel").all())
    sightings = list(
        effort.sightings.select_related("species").order_by("sighting_time", "id")
    )
    # One query for the whole day, in time order, from the view.
    timeline = list(effort.timeline.all())
    history, record_actions = record_history("daily_effort", legacy_id)

    context = {
        "section": "efforts",
        "effort": effort,
        "tracks": tracks,
        "sightings": sightings,
        "timeline": timeline,
        "species_seen": species_seen(sightings),
        "history": history,
        "record_actions": record_actions,
        "distance": compare_distance(effort, tracks),
        "track_geojson_url": f"/api/track/{tracks[0].legacy_track_id}/"
                             if tracks and tracks[0].legacy_track_id else None,
        # A corrupted line runs off across the ocean. It is still drawn,
        # because it is what the database holds, but the map is framed on
        # the sightings instead so the page stays readable.
        "track_is_suspect": bool(tracks) and tracks[0].length_is_plausible is False,
        # Only for efforts with no GPS file. The timeline is already loaded,
        # so this costs nothing and is worked out per request rather than
        # stored, which is what the old reconstructed_path column did.
        "interpolated_path": None if tracks else [
            [float(row.lat), float(row.lon)]
            for row in timeline if row.lat is not None and row.lon is not None
        ],
    }

    template = "survey/effort_detail.html"
    return render(request, template, context)


def species_seen(sightings):
    """What was seen on an effort, one row per species."""
    counts = {}
    for sighting in sightings:
        name = str(sighting.species) if sighting.species_id else "Not identified"
        row = counts.setdefault(name, {"name": name, "count": 0, "animals": 0})
        row["count"] += 1
        row["animals"] += sighting.est_size_best or 0
    return sorted(counts.values(), key=lambda r: (-r["count"], r["name"]))


def compare_distance(effort, tracks):
    """Recorded distance against the length of the GPS track.

    Returns None when there is nothing to compare, and a dict carrying a
    reason instead of a number when the track length cannot be trusted.
    Seven tracks have corrupted geometry giving lengths up to 56,060 nautical
    miles; showing "difference: 55,991 nm" would be worse than showing
    nothing.
    """
    recorded = effort.distance_recorded_nm
    usable = [t for t in tracks if t.length_nm is not None]

    if recorded is None and not usable:
        return None

    if not usable:
        return {"recorded": recorded, "track": None}

    track = usable[0]
    if track.length_is_plausible is False:
        return {
            "recorded": recorded,
            "track": None,
            "note": (
                f"The track's recorded length of {track.length_nm:,.1f} nm over "
                f"{track.duration_hours:.1f} hours implies "
                f"{track.implied_speed_kn:,.0f} knots, so its geometry is "
                "corrupted and the comparison is not shown."
            ),
        }
    if track.length_is_plausible is None:
        return {
            "recorded": recorded,
            "track": track.length_nm,
            "difference": None,
            "note": ("The track has no start and end time, so its length "
                     "could not be checked for plausibility."),
        }

    if recorded is None:
        return {"recorded": None, "track": track.length_nm,
                "note": "No distance was recorded for this effort."}

    difference = track.length_nm - recorded
    percent = (float(difference) / float(recorded) * 100) if recorded else None
    return {
        "recorded": recorded,
        "track": track.length_nm,
        "difference": difference,
        "percent": percent,
    }


# Sightings

SIGHTING_SORTS = {
    "date": "sighting_date",
    "time": "sighting_time",
    "id": "legacy_sighting_id",
    "species": "species__common_name",
    "vessel": "vessel__name",
    "size": "est_size_best",
    "position_type": "position_type",
}

@login_required
def sighting_list(request):
    queryset = Sighting.objects.select_related(
        "species", "vessel", "daily_effort"
    )

    error = None
    try:
        queryset, applied, excluded = filter_sightings(queryset, request.GET)
    except ValueError as exc:
        error, applied, excluded = str(exc), [], 0

    queryset, sort_key, sort_desc = apply_sort(queryset, request, SIGHTING_SORTS, "-date")
    page, per_page = paginate(request, queryset)

    # See the note in views/efforts.py: a filter set that could not be read
    # must not become the export's stored state.
    if not error:
        remember_export_state(request, "sightings", request.GET, page.paginator.count)

    include_non_animal = request.GET.get("include_non_animal") == "1"

    return render(request, "survey/sighting_list.html", {
        "section": "sightings",
        "page": page,
        "per_page": per_page,
        "page_sizes": PAGE_SIZES,
        "sort_key": sort_key,
        "sort_desc": sort_desc,
        "applied": applied,
        "excluded_no_position": excluded,
        "error": error,
        "options": filter_options(),
        "species_list": species_choices(include_non_animal),
        "include_non_animal": include_non_animal,
        "params": request.GET,
        "selected": {
            "species": request.GET.getlist("species"),
            "vessels": request.GET.getlist("vessel"),
            "months": request.GET.getlist("month"),
            "years": request.GET.getlist("year"),
        },
    })


@login_required
def sighting_detail(request, legacy_id):
    try:
        sighting = Sighting.objects.select_related(
            "species", "vessel", "daily_effort", "daily_effort__vessel"
        ).get(legacy_sighting_id=legacy_id)
    except Sighting.DoesNotExist:
        raise Http404(f"No sighting with identifier {legacy_id}")

    samples = list(sighting.samples.select_related("species").all())
    history, record_actions = record_history("sighting", legacy_id)

    effort = sighting.daily_effort
    track_id = None
    if effort:
        track = effort.tracks.filter(geom__isnull=False).first()
        track_id = track.legacy_track_id if track else None

    context = {
        "section": "sightings",
        "sighting": sighting,
        "effort": effort,
        "samples": samples,
        "history": history,
        "record_actions": record_actions,
        "attached": _attached_records(sighting),
        "track_geojson_url": f"/api/track/{track_id}/" if track_id else None,
    }

    template = "survey/sighting_detail.html"
    return render(request, template, context)


def _attached_records(sighting):
    """
    The records attached to a sighting, from the tables that hold them.

    V1 kept these as a JSON blob on the sighting, because its import did not
    carry the child tables across. They are real tables now, so this reads
    them, and there is nothing to flatten or guess the shape of.
    """
    groups = []
    for table, label, columns in [
        ("SightingEventT", "Sighting events",
         ['"EventTime"', '"SightEvent"', '"Field ID"', '"Reaction"',
          '"NumReact"', '"Range"', '"SightEventComments"']),
        ("OtherSpeciesT", "Other species present",
         ['"Species"', '"Class"', '"Count"', '"Comments"']),
        ("TagSummaryT", "Tag deployments",
         ['"Tag#"', '"TagType"', '"DeployBodyLoc"', '"DeployDateTime"',
          '"DeployRxn"', '"HoursTotal"', '"TagComments"']),
    ]:
        with connection.cursor() as cur:
            if table == "TagSummaryT":
                # TagSummaryT has no working effort or sighting link, so it is
                # reached by the natural key DB167's own views use.
                cur.execute(f"""
                    SELECT {", ".join(columns)} FROM dbo."TagSummaryT" t
                    WHERE t."Research Group" = %s AND t."Vessel" = %s
                      AND t."Date"::date = %s AND t."Sighting" = %s
                """, [sighting.research_group, _vessel_text(sighting),
                      sighting.sighting_date, sighting.sighting_number])
            else:
                cur.execute(f"""
                    SELECT {", ".join(columns)} FROM dbo."{table}"
                    WHERE sighting_id = %s
                """, [sighting.legacy_sighting_id])
            names = [c[0] for c in cur.description]
            rows = cur.fetchall()
        rows = [r for r in rows if any(v not in (None, "") for v in r)]
        if rows:
            groups.append({"label": label, "columns": names, "rows": rows})

    with connection.cursor() as cur:
        cur.execute("""
            SELECT "CRC ID", "Field ID", "Species"
            FROM   dbo."SightingIdentificationT"
            WHERE  "SightingID" = %s ORDER BY "CRC ID"
        """, [sighting.legacy_sighting_id])
        identifications = cur.fetchall()
    if identifications:
        groups.append({"label": "Individuals identified",
                       "columns": ["CRC ID", "Field ID", "Species"],
                       "rows": identifications})
    return groups


def _vessel_text(sighting):
    """The vessel exactly as the sighting records it, for a natural-key join."""
    with connection.cursor() as cur:
        cur.execute('SELECT "Vessel" FROM dbo."SightingT" WHERE "SightingID" = %s',
                    [sighting.legacy_sighting_id])
        row = cur.fetchone()
    return row[0] if row else None

FORMATS = ["csv", "excel", "geojson"]

AREA_LABELS = {
    "explore": "Explore",
    "efforts": "Efforts",
    "sightings": "Sightings",
}

# Explore and Sightings both export sightings; Efforts exports efforts.
AREA_RECORD = {"explore": "sightings", "sightings": "sightings",
               "efforts": "efforts"}


@login_required
def export_page(request):
    state = export_state(request)

    areas = []
    for area in EXPORT_AREAS:
        entry = state[area]
        areas.append({
            "key": area,
            "label": AREA_LABELS[area],
            "record": AREA_RECORD[area],
            "count": entry["count"],
            "filters": entry["filters"],
            "visited": entry["count"] is not None,
        })

    return render(request, "survey/export.html", {
        "section": "export",
        "areas": areas,
        "optional_fields": OPTIONAL_SIGHTING_FIELDS,
        "formats": FORMATS,
    })


@login_required
def export_download(request):
    area = request.GET.get("area")
    if area not in EXPORT_AREAS:
        return HttpResponseBadRequest("Choose one of the three areas to export.")

    fmt = request.GET.get("format", "csv")
    if fmt not in FORMATS:
        return HttpResponseBadRequest(f"Unknown format {fmt}.")

    state = export_state(request)[area]
    filters = QueryDict(mutable=True)
    for key, values in state["filters"].items():
        # Sessions saved before lists were stored hold a plain string.
        filters.setlist(key, values if isinstance(values, list) else [values])
    record_type = AREA_RECORD[area]

    # The stored filters were readable when they were stored, but a session
    # can outlive a code change, so a failure here answers plainly rather
    # than turning into a server error over a download.
    try:
        if record_type == "efforts":
            queryset = DailyEffort.objects.select_related("vessel")
            queryset, _applied, _excluded = filter_efforts(queryset, filters)
            lat_field, lon_field = "start_lat", "start_lon"
        else:
            queryset = Sighting.objects.select_related(
                "species", "vessel", "daily_effort"
            )
            queryset, _applied, _excluded = filter_sightings(queryset, filters)
            lat_field, lon_field = "lat", "lon"
    except ValueError as exc:
        return HttpResponseBadRequest(
            f"The saved filters for {AREA_LABELS[area]} could not be used: "
            f"{exc} Open that page again to reset them."
        )

    # A download from one effort or sighting page exports that record alone,
    # not whatever the list happened to be showing.
    one = request.GET.get("one")
    if one:
        field = ("legacy_daily_effort_id" if record_type == "efforts"
                 else "legacy_sighting_id")
        queryset = queryset.model.objects.filter(**{field: one})
        if not queryset.exists():
            raise Http404(one)

    columns = columns_for(record_type, request.GET.getlist("field"))

    # The area is named only where it differs from the record type, so an
    # export of sightings from the Sightings list is not called
    # "sightings_sightings".
    source = record_type if area == record_type else f"{record_type}_from_{area}"
    filename = f"cascadia_{source}_{datetime.date.today().isoformat()}"

    if fmt == "csv":
        response = csv_response(queryset, columns, filename)
    elif fmt == "excel":
        response = excel_response(queryset, columns, filename)
    else:
        response = geojson_response(queryset, columns, filename,
                                    lat_field, lon_field)

    if request.GET.get("tracks") == "1":
        return zip_with_tracks(response, queryset, record_type, filename)
    return response


def zip_with_tracks(response, queryset, record_type, filename):
    """The data file plus a tracks folder, as one zip.

    The point of the export is that an analyst gets the positions and the GPS
    behind them together. The files come from object storage at full
    resolution, not from the simplified geometry in the database.
    """
    efforts = (queryset if record_type == "efforts"
               else DailyEffort.objects.filter(
                   id__in=queryset.values("daily_effort_id")))
    keys = list(
        Track.objects.filter(daily_effort__in=efforts, object_key__isnull=False)
        .order_by().values_list("object_key", flat=True).distinct()
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        name = response["Content-Disposition"].split("filename=")[-1].strip('"')
        archive.writestr(name, response.content)
        for key, body in track_objects.fetch(keys):
            archive.writestr(f"tracks/{key}", body)
        if not track_objects.configured():
            archive.writestr(
                "tracks/README.txt",
                "The GPS files were not included because object storage is not "
                "configured on this server. Set SEDB_BUCKET_URL for a public "
                "bucket, or SEDB_BUCKET_ENDPOINT with SEDB_BUCKET_KEY and "
                "SEDB_BUCKET_SECRET for a private one.\n"
                f"{len(keys)} track files belong to this export.\n")

    zipped = HttpResponse(buffer.getvalue(), content_type="application/zip")
    zipped["Content-Disposition"] = f'attachment; filename="{filename}.zip"'
    return zipped


# JSON the maps load

class SimplifyPreserveTopology(Func):
    """PostGIS ST_SimplifyPreserveTopology.

    Django ships wrappers for most PostGIS functions but not this one, and
    the topology-preserving variant is the one worth having: plain
    ST_Simplify can turn a track into an invalid line.
    """

    function = "ST_SimplifyPreserveTopology"
    output_field = GeometryField(srid=4326)

# About 550 m at this latitude. The database already holds a line simplified
# to roughly 11 m; this is the further reduction that gets every track on the
# Explore map into well under half a megabyte.
EXPLORE_TOLERANCE = 0.005

# Five decimal places is a little over a metre, which is finer than the
# source data supports. Beyond that is noise, and a third of the payload.
COORD_PLACES = 5


# How many rows either results tab lists before it asks you to narrow down.
RESULTS_SHOWN = 300


@login_required
def efforts_json(request):
    """The efforts behind the current filters, for the Explore results tab.

    Fetched the first time that tab is opened rather than with the page, so
    somebody who only ever looks at sightings never pays for this query.
    """
    try:
        efforts, _applied, _excluded = filter_efforts(DailyEffort.objects.all(),
                                                      request.GET)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    total = efforts.count()
    rows = list(
        efforts.select_related("vessel")
        .annotate(sighting_count=Count("sightings", distinct=True))
        .order_by("-effort_date")
        .values_list("legacy_daily_effort_id", "effort_date", "locality",
                     "vessel__code", "sighting_count")[:RESULTS_SHOWN]
    )
    return JsonResponse({
        "cols": ["id", "date", "locality", "vessel", "sightings"],
        "rows": [[i, str(d) if d else "", loc or "", v or "", n]
                 for i, d, loc, v, n in rows],
        "total": total,
    })


@login_required
def sightings_json(request):
    """Every matching sighting as a compact array.

    Not GeoJSON: the field names would repeat 31,000 times and cost several
    times the size for no benefit. The columns are named once, in `cols`.
    """
    queryset = Sighting.objects.filter(geom__isnull=False)

    try:
        queryset, _applied, _excluded = filter_sightings(queryset, request.GET)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    rows = [
        [
            legacy_id,
            round(float(lon), COORD_PLACES),
            round(float(lat), COORD_PLACES),
            species_id,
            date.year if date else None,
            size,
        ]
        for legacy_id, lon, lat, species_id, date, size in (
            queryset.order_by().values_list(
                "legacy_sighting_id", "lon", "lat", "species_id",
                "sighting_date", "est_size_best",
            )
        )
        if lon is not None and lat is not None
    ]

    return JsonResponse(
        {"cols": ["id", "lon", "lat", "species", "year", "size"], "rows": rows}
    )


@login_required
def tracks_json(request):
    """Every matching track as GeoJSON, simplified for the whole-region view."""
    queryset = Track.objects.filter(geom__isnull=False)

    try:
        efforts, _applied, _excluded = filter_efforts(DailyEffort.objects.all(),
                                                      request.GET)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    # Tracks are filtered through the effort each belongs to, so the lines
    # drawn always describe the same efforts as the sightings beside them.
    queryset = queryset.filter(daily_effort__in=efforts)

    rows = (
        queryset.order_by()
        .annotate(
            geojson=AsGeoJSON(
                SimplifyPreserveTopology("geom", EXPLORE_TOLERANCE),
                precision=4,
            )
        )
        .values_list(
            "legacy_track_id", "daily_effort__legacy_daily_effort_id", "geojson",
            "survey_date", "object_key"
        )
    )

    # The date and file name are here so the browser can build the track
    # picker from this response. Listing every track in the page instead would
    # be another query and another few thousand options nobody scrolls.
    features = [
        {
            "type": "Feature",
            "properties": {
                "track": track_id,
                "effort": effort_id,
                "label": f"{survey_date} {os.path.basename(key or '')}".strip(),
            },
            "geometry": json.loads(geojson),
        }
        for track_id, effort_id, geojson, survey_date, key in rows
        if geojson
    ]

    return JsonResponse({"type": "FeatureCollection", "features": features})


@login_required
def track_full_json(request, legacy_id):
    """One track at the resolution held in the database.

    The stored line is simplified to roughly 11 m, which is the accuracy the
    effort detail page shows. The original full resolution file lives in
    object storage under track.object_key and is not read here.
    """
    row = (
        Track.objects.filter(legacy_track_id=legacy_id, geom__isnull=False)
        .annotate(geojson=AsGeoJSON("geom", precision=6))
        .values("legacy_track_id", "geojson", "length_nm", "point_count")
        .first()
    )
    if not row:
        raise Http404(f"No track geometry for {legacy_id}")

    return JsonResponse({
        "type": "Feature",
        "properties": {
            "track": row["legacy_track_id"],
            "length_nm": (float(row["length_nm"])
                          if row["length_nm"] is not None else None),
            "point_count": row["point_count"],
        },
        "geometry": json.loads(row["geojson"]),
    })
