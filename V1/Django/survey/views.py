"""Every page the survey site serves.

Each view assembles what its template needs, so no template can trigger a
query. Filtering lives in filters.py because Explore, Efforts and Sightings
all have to filter the same way, and the export has to match the list it came
from.
"""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.gis.db.models import GeometryField
from django.contrib.gis.db.models.functions import AsGeoJSON
from django.core.cache import cache
from django.db.models import Count, Func, Q
from django.db import connection
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render

from .export_stack import filter_string
from .filters import (NON_ANIMAL, filter_efforts, filter_sightings,
                      research_group_choice, species_choices)
from .history import record_history
from .models import (DailyCondition, DailyEffort, DailyEvent,
                     Sighting, Species, Track)
from .services import (COLOUR_PROFILE_COOKIE, COLOUR_PROFILES, PAGE_SIZES, apply_sort,
                       colour_profile, filter_options, filter_options_for,
                       paginate)

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

    include_non_animal = request.GET.get("include_non_animal") == "1"
    options = filter_options_for(request.GET)

    return render(request, "survey/explore.html", {
        "section": "explore",
        "options": options,
        "species_list": species_choices(include_non_animal, options),
        "include_non_animal": include_non_animal,
        "species_meta": species_meta(colour_profile(request)),
        "legend": legend_entries(options),
        "sighting_count": sighting_count,
        "effort_count": effort_count,
        "applied": applied,
        "excluded_no_position": excluded,
        "error": error,
        "params": request.GET,
        "export_qs": filter_string(request.GET),
        "selected": selected_filters(request),
        "research_group": research_group_choice(request.GET),
    })


def selected_filters(request):
    """Every value of each filter that takes several, so the template marks
    all of them selected, not just the last."""
    get = request.GET.getlist
    return {
        "species": get("species"),
        "vessels": get("vessel"),
        "months": get("month"),
        "years": get("year"),
        "research_groups": get("research_group"),
        "sub_areas": get("sub_area"),
        "projects": get("project_objective"),
    }


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


def legend_entries(options=None):
    """One row per animal group that has sightings, in the picker's order."""
    return [g for g in (options or filter_options())["species_groups"]
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
        "options": filter_options_for(request.GET, "efforts"),
        "params": request.GET,
        "export_qs": filter_string(request.GET),
        "selected": selected_filters(request),
        "research_group": research_group_choice(request.GET),
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
    history, record_actions = record_history("daily_effort", effort.pk)

    context = {
        "section": "efforts",
        "effort": effort,
        "tracks": tracks,
        "sightings": sightings,
        "timeline": timeline,
        # What the Track File Manager can make a track from (datahealth/trackfix.py).
        "positioned_count": sum(1 for r in timeline if r.at and r.lat is not None and r.lon is not None),
        "species_seen": species_seen(sightings),
        "history": history,
        "record_actions": record_actions,
        "distance": compare_distance(effort, tracks),
        # Every track with a line is drawn, each with the popup Explore
        # shows. An Effort can have several, one per GPS device or file.
        "map_tracks": [
            {"track": t.legacy_track_id, **track_popup_fields(t, effort)}
            for t in tracks if t.legacy_track_id and t.geom
        ],
        # A corrupted line runs off across the ocean. It is still drawn,
        # because it is what the database holds, but the map is framed on
        # the sightings instead so the page stays readable.
        "track_is_suspect": any(t.length_is_plausible is False for t in tracks),
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

    include_non_animal = request.GET.get("include_non_animal") == "1"
    options = filter_options_for(request.GET)

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
        "options": options,
        "species_list": species_choices(include_non_animal, options),
        "include_non_animal": include_non_animal,
        "params": request.GET,
        "export_qs": filter_string(request.GET),
        "selected": selected_filters(request),
        "research_group": research_group_choice(request.GET),
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
    history, record_actions = record_history("sighting", sighting.pk)

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
        ("SightingEventT", "Sighting Events",
         ['"EventTime"', '"SightEvent"', '"Field ID"', '"Reaction"',
          '"NumReact"', '"Range"', '"SightEventComments"']),
        ("OtherSpeciesT", "Other Species Present",
         ['"Species"', '"Class"', '"Count"', '"Comments"']),
        ("TagSummaryT", "Tag Deployments",
         ['"Tag#"', '"TagType"', '"DeployBodyLoc"', '"DeployDateTime"',
          '"DeployRxn"', '"HoursTotal"', '"TagComments"']),
    ]:
        # Each table has its Foreign Key to the sighting, sighting_id.
        with connection.cursor() as cur:
            cur.execute(f"""
                SELECT {", ".join(columns)} FROM dbo."{table}"
                WHERE sighting_id = %s
            """, [sighting.pk])
            names = [c[0] for c in cur.description]
            rows = cur.fetchall()
        rows = [r for r in rows if any(v not in (None, "") for v in r)]
        if rows:
            groups.append({"label": label, "columns": names, "rows": rows})

    # The animals identified, from IdentificationT and the catalogue of known
    # animals, IndividualT. SightingIdentificationT, an old copy DB167 stopped
    # updating, stays in raw.
    with connection.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT coalesce(n."CRC ID", i."CRC ID") AS "CRC ID", i."Field ID",
                   coalesce(n."Species", i."Species") AS "Species"
            FROM   dbo."IdentificationT" i
            LEFT   JOIN dbo."IndividualT" n ON n."IndividualID" = i."IndividualID"
            WHERE  i.sighting_id = %s
            ORDER  BY 1, 2
        """, [sighting.pk])
        identifications = cur.fetchall()
    if identifications:
        groups.append({"label": "Individuals Identified",
                       "columns": ["CRC ID", "Field ID", "Species"],
                       "rows": identifications})
    return groups


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

    tracks = (
        queryset.order_by()
        .select_related("daily_effort__vessel")
        .only(
            "legacy_track_id", "object_key", "survey_date", "research_group",
            "point_count", "length_nm", "start_time_utc", "end_time_utc",
            "daily_effort", "daily_effort__legacy_daily_effort_id",
            "daily_effort__effort_date", "daily_effort__research_group",
            "daily_effort__vessel", "daily_effort__vessel__name",
            "daily_effort__vessel__code",
        )
        .annotate(
            geojson=AsGeoJSON(
                SimplifyPreserveTopology("geom", EXPLORE_TOLERANCE),
                precision=4,
            )
        )
    )

    # The date and file name are here so the browser can build the track
    # picker from this response. Listing every track in the page instead would
    # be another query and another few thousand options nobody scrolls.
    # The rest is what the popup shows when a track is clicked, so clicking
    # one costs no request.
    features = [
        {
            "type": "Feature",
            "properties": {
                "track": track.legacy_track_id,
                "effort": track.daily_effort.legacy_daily_effort_id,
                "label": f"{track.survey_date} {track.file_name or ''}".strip(),
                **track_popup_fields(track, track.daily_effort),
            },
            "geometry": json.loads(track.geojson),
        }
        for track in tracks
        if track.geojson
    ]

    # Without the spaces json.dumps puts after every comma and colon, which
    # across every coordinate pair is more than the popup fields add.
    return JsonResponse({"type": "FeatureCollection", "features": features},
                        json_dumps_params={"separators": (",", ":")})


def track_popup_fields(track, effort):
    """What a track's popup on a map shows, as short JSON keys.

    The vessel and date are the Effort's, because the popup describes the
    Effort the track belongs to. A length the track's own times show to be
    impossible is flagged, so a corrupted 56,000 nm line is not read as real.
    The flag is left out when it is false, which is nearly every track.
    """
    vessel = effort.vessel if effort and effort.vessel_id else None
    fields = {
        "date": str(effort.effort_date) if effort and effort.effort_date else None,
        "vessel": vessel.label if vessel else None,
        "group": track.research_group or (effort.research_group if effort else None),
        "object_key": track.object_key,
        "points": track.point_count,
        "length_nm": (round(float(track.length_nm), 1)
                      if track.length_nm is not None else None),
    }
    if track.length_is_plausible is False:
        fields["suspect"] = True
    return fields


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


@login_required
def settings_page(request):
    """The reader's own settings. Each is a cookie, so it belongs to the
    browser it was chosen in and needs nothing stored in the database."""
    if request.method == "POST":
        profile = request.POST.get("colour_profile")
        if profile in COLOUR_PROFILES:
            response = redirect("settings")
            response.set_cookie(COLOUR_PROFILE_COOKIE, profile, max_age=365 * 24 * 3600,
                                samesite="Lax", secure=request.is_secure())
            messages.success(request, "Settings saved.")
            return response
        messages.error(request, "Choose a color profile.")
        return redirect("settings")
    return render(request, "survey/settings.html", {"section": "settings"})
