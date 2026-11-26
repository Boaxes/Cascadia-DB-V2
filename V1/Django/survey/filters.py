"""Turning request parameters into queryset filters.

Kept apart from the views because the list page, the Explore map and the
export all have to filter the same way. If they drifted, an export would not
match the list it came from.

Each function returns the filtered queryset plus a description of what was
applied, which the pages use to say what the reader is looking at.
"""

from django.db.models import BooleanField, F, Func

from . import sub_areas
from .services import filter_options, parse_polygon


def _ints(params, name):
    """
    Every value given for one filter, as integers.

    The species and vessel filters accept more than one selection, so the same
    name appears several times in the query string. getlist reads them all; a
    plain get would read only the last, which is what made choosing three
    species silently show one.
    """
    getlist = getattr(params, "getlist", None)
    values = getlist(name) if getlist else [params.get(name)]
    return [int(v) for v in values if v not in (None, "") and str(v).lstrip("-").isdigit()]


def _strings(params, name):
    """Every value given for one filter, as text, once each, in the order given."""
    getlist = getattr(params, "getlist", None)
    values = getlist(name) if getlist else [params.get(name)]
    out = []
    for v in values:
        v = (v or "").strip()
        if v and v not in out:
            out.append(v)
    return out


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _date(value):
    """A YYYY-MM-DD string, or None. Anything else is ignored rather than
    raising, so a half typed date does not break the page."""
    if not value:
        return None
    from datetime import date

    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _describe(parts):
    return [p for p in parts if p]


MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _spans(numbers, name):
    """Sorted numbers as runs: 2014-2016, 2019. Months read Apr-Jun."""
    runs = []
    for n in numbers:
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    return ", ".join(name(a) if a == b else f"{name(a)}\u2013{name(b)}" for a, b in runs)


def _filter_time(queryset, params, field, applied):
    """Exact dates, any set of years, and any set of months.

    The months apply within every chosen year, so "November, 2014 to 2024" or
    "April to June of every year" is one filter.
    """
    date_from = _date(params.get("date_from"))
    date_to = _date(params.get("date_to"))
    if date_from:
        queryset = queryset.filter(**{f"{field}__gte": date_from})
        applied.append(f"from {date_from}")
    if date_to:
        queryset = queryset.filter(**{f"{field}__lte": date_to})
        applied.append(f"to {date_to}")

    years = sorted({y for y in _ints(params, "year") if 1900 < y < 2200})
    year_to = _int(params.get("year_to"))   # links from before the year chips
    if len(years) == 1 and year_to:
        years = list(range(min(years[0], year_to), max(years[0], year_to) + 1))
    if years:
        queryset = queryset.filter(**{f"{field}__year__in": years})
        applied.append(("year " if len(years) == 1 else "years ") + _spans(years, str))

    months = sorted({m for m in _ints(params, "month") if 1 <= m <= 12})
    if 0 < len(months) < 12:
        queryset = queryset.filter(**{f"{field}__month__in": months})
        applied.append("in " + _spans(months, lambda m: MONTH_NAMES[m - 1]))
    return queryset


# ---------------------------------------------------------------------------
# Efforts
# ---------------------------------------------------------------------------


# Research group. Every research group's records are in the database, but
# the website shows CRC's unless asked otherwise: with no research_group in
# the link the filter is CRC, research_group=all removes it, and any other
# values are the groups chosen. Every page, API and export reads it here, so
# none can drift from the others.

DEFAULT_RESEARCH_GROUP = "CRC"
ALL_RESEARCH_GROUPS = "all"


def research_group_choice(params):
    """{"groups": the chosen groups, or None for every group, "default": True
    when nothing was chosen, "label": what the panel shows}."""
    values = _strings(params, "research_group")
    if ALL_RESEARCH_GROUPS in values:
        return {"groups": None, "default": False, "label": "All Research Groups"}
    if not values:
        return {"groups": [DEFAULT_RESEARCH_GROUP], "default": True,
                "label": f"{DEFAULT_RESEARCH_GROUP} (Default)"}
    label = ", ".join(values[:3]) + (f" and {len(values) - 3} more" if len(values) > 3 else "")
    return {"groups": values, "default": False, "label": label}


def _filter_research_group(queryset, params, field, applied):
    choice = research_group_choice(params)
    groups = choice["groups"]
    if groups is None:
        applied.append("from every Research Group")
        return queryset
    queryset = queryset.filter(**{f"{field}__in": groups})
    applied.append(("from Research Group " if len(groups) == 1
                    else "from Research Groups ") + choice["label"])
    return queryset


def _filter_sub_area(queryset, params, field, applied):
    """Any of the chosen sub-areas. A corrected sub-area matches every way it
    is spelled in the data."""
    names = _strings(params, "sub_area")
    if names:
        known = filter_options()["sub_area_values"]
        values = sorted({v for name in names for v in sub_areas.matching_values(name, known)})
        queryset = queryset.filter(**{f"{field}__in": values})
        applied.append(f"sub-area {names[0]}" if len(names) == 1 else f"{len(names)} sub-areas")
    return queryset


def _filter_project(queryset, params, field, applied):
    """Any of the chosen projects. The pipeline makes their spelling
    consistent, so each is matched exactly."""
    names = _strings(params, "project_objective")
    if names:
        queryset = queryset.filter(**{f"{field}__in": names})
        applied.append(f"project {names[0]}" if len(names) == 1 else f"{len(names)} projects")
    return queryset


# Tags and samples: each With, Without or Either (no parameter). Both are
# EXISTS subqueries on the dbo table, which stop at the first row found and
# never repeat a record the way a join would. The record's own id goes in as
# an expression rather than as text, so Django still names it correctly when
# the query is nested inside another (the tracks API does that).
#
# An effort has tags when a TagSummaryT row names the effort or one of its
# sightings, and samples the same way through SampleT. A sighting has them
# when a row names the sighting.
#
# The two ways of naming an effort sit in one UNION ALL inside one EXISTS.
# Written as two EXISTS joined by OR, PostgreSQL guessed the query cost in
# the millions and spent over half a second compiling it, for 12 ms of work.
_EFFORT_NAMED = (
    'EXISTS (SELECT 1 FROM ('
    'SELECT r.daily_effort_id FROM dbo."{table}" r'
    ' UNION ALL SELECT rs.daily_effort_id FROM dbo."{table}" r'
    ' JOIN dbo."SightingT" rs ON rs.id = r.sighting_id'
    ') named WHERE named.daily_effort_id = %(expressions)s)'
)
_SIGHTING_NAMED = 'EXISTS (SELECT 1 FROM dbo."{table}" r WHERE r.sighting_id = %(expressions)s)'

WITH_OR_WITHOUT = {"tags": ("TagSummaryT", "Tags"), "samples": ("SampleT", "Samples")}


def _filter_with_or_without(queryset, params, template, applied):
    for name, (table, label) in WITH_OR_WITHOUT.items():
        value = params.get(name)
        if value not in ("with", "without"):
            continue
        named = Func(F("id"), template=template.format(table=table), output_field=BooleanField())
        queryset = queryset.filter(named) if value == "with" else queryset.exclude(named)
        applied.append(f"{value} {label}")
    return queryset


MATCH_SIGHTINGS = "match_sightings"


def match_sightings_ticked(params):
    """Whether Only Efforts With Matching Sightings is ticked. It is the
    default, so only an explicit 0 turns it off. The panel sends 0 first and
    the checkbox's 1 after it, so the last value is the one the reader chose."""
    getlist = getattr(params, "getlist", None)
    values = getlist(MATCH_SIGHTINGS) if getlist else [params.get(MATCH_SIGHTINGS)]
    return not values or values[-1] != "0"


def uncertain_choice(params):
    """The Uncertain Species choice: "exclude", "only", or None for Include
    (the default, nothing sent). The old checkbox sent 1, which means Only."""
    value = (params.get("uncertain") or "").strip()
    return {"1": "only", "only": "only", "exclude": "exclude"}.get(value)


def sighting_filter_active(params):
    """Whether any filter that only a sighting can answer is set. A filter
    added later that efforts cannot answer is one more line here. The default
    exclusion of non-animal records is not a filter the reader set."""
    return bool(
        _ints(params, "species")
        or (params.get("position_type") or "").strip()
        or uncertain_choice(params)
        or params.get("land") in LAND_CHOICES
    )


def filter_efforts(queryset, params):
    """Narrow a queryset of efforts by the filters on the page.

    Returns (queryset, applied, excluded_no_position). The last is the number
    of efforts dropped purely for having no position when an area filter is
    active, which the page reports rather than letting them vanish.
    """
    applied = []
    excluded_no_position = 0

    queryset = _filter_research_group(queryset, params, "research_group", applied)
    queryset = _filter_time(queryset, params, "effort_date", applied)

    locality = (params.get("locality") or "").strip()
    if locality:
        queryset = queryset.filter(locality=locality)
        applied.append(f"locality {locality}")

    region = (params.get("region") or "").strip()
    if region:
        queryset = queryset.filter(region=region)
        applied.append(f"region {region}")

    queryset = _filter_sub_area(queryset, params, "sub_area", applied)

    survey_type = (params.get("survey_type") or "").strip()
    if survey_type:
        queryset = queryset.filter(survey_type=survey_type)
        applied.append(f"survey type {survey_type}")

    vessels = _ints(params, "vessel")
    if vessels:
        queryset = queryset.filter(vessel_id__in=vessels)
        applied.append("vessel" if len(vessels) == 1 else f"{len(vessels)} vessels")

    # Crew is free text with 1,602 distinct values mixing initials and full
    # names, so there is no dropdown to offer.
    crew = (params.get("crew") or "").strip()
    if crew:
        queryset = queryset.filter(personnel__icontains=crew)
        applied.append(f'crew containing "{crew}"')

    queryset = _filter_project(queryset, params, "project_objective", applied)
    queryset = _filter_with_or_without(queryset, params, _EFFORT_NAMED, applied)

    queryset, track_note = _filter_effort_track_status(queryset, params.get("track"))
    if track_note:
        applied.append(track_note)

    area = parse_polygon(params.get("area"))
    if area:
        excluded_no_position = queryset.filter(start_point__isnull=True).count()
        queryset = queryset.filter(start_point__within=area)
        applied.append("inside the drawn area")

    # A sighting filter would otherwise move the sighting count and leave the
    # effort count alone. filter_sightings never calls back here.
    if match_sightings_ticked(params) and sighting_filter_active(params):
        from .models import Sighting
        matching = filter_sightings(Sighting.objects.all(), params)[0]
        queryset = queryset.filter(pk__in=matching.order_by().values("daily_effort_id"))
        applied.append("with a matching sighting")

    return queryset, _describe(applied), excluded_no_position


def _filter_effort_track_status(queryset, value, via="tracks"):
    """
    The GPS track filter, in the Track File Manager's words.

    An effort is Available (a matched track whose file has points), Blank (a
    matched track whose file has none), or has No track file. A file no effort
    has is not something an effort can be filtered by. Worked out from the
    file's points rather than the stored status alone, the same way the
    Track File Manager does it.
    """
    from .models import Track
    has_file = {f"{via}__track_status__in": Track.HAS_FILE}
    if value == "none":
        return queryset.filter(**{f"{via}__isnull": True}), "with no track file"
    if value == "any":
        return queryset.filter(**{f"{via}__isnull": False}).distinct(), "with a track record"
    if value == "available":
        return queryset.filter(**has_file).distinct(), "with their track file"
    if value == "blank":
        return (queryset.filter(**{f"{via}__isnull": False}).exclude(**has_file).distinct(),
                "whose track file is blank")
    return queryset, None


# ---------------------------------------------------------------------------
# Sightings
# ---------------------------------------------------------------------------

# Ship, Boat and OTHER live in the species column. They are real records but
# they are not animals, so they are out of the way unless asked for.
NON_ANIMAL = "non_animal"


def _filter_sighting_track_status(queryset, value):
    """The track filter, reaching a sighting through the day it belongs to."""
    return _filter_effort_track_status(queryset, value, via="daily_effort__tracks")


# Sightings on Land. A sighting is on land when it is inside a land polygon
# (Natural Earth 1:10m, loaded by manage.py load_land) and more than the margin
# from the coastline. The coastline is coarse, so a position a little way
# inside it is still counted as at sea. The land test goes first and looks only
# at the pieces of the position's own one-degree cell; the distance, measured in metres on the spheroid, is asked only of the
# few sightings that fall inside land. It is one EXISTS, so that Only is a
# semi join and Exclude an anti join, which PostgreSQL answers one sighting at a
# time. A sighting with no position is never on land.
LAND_MARGIN_METRES = 1000
LAND_CHOICES = {"exclude": "excluding sightings on land", "only": "only sightings on land"}
_ON_LAND = (
    "EXISTS (SELECT 1 FROM public.land_area la"
    " WHERE la.cell = floor(ST_X(%(expressions)s) + 180)::int * 1000 + floor(ST_Y(%(expressions)s) + 90)::int"
    " AND la.geom && %(expressions)s AND ST_Intersects(la.geom, %(expressions)s)"
    " AND NOT EXISTS (SELECT 1 FROM public.land_coast lc"
    " WHERE ST_DWithin(lc.geom, %(expressions)s::geography, {margin})))"
).format(margin=LAND_MARGIN_METRES)


def _land_loaded():
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass('public.land_area') IS NOT NULL"
                    " AND to_regclass('public.land_coast') IS NOT NULL")
        return cur.fetchone()[0]


def _filter_land(queryset, params, applied):
    choice = params.get("land")
    if choice not in LAND_CHOICES:
        return queryset
    if not _land_loaded():
        raise ValueError("The land outline is not loaded in this database, "
                         "so Sightings on Land cannot be used. Run manage.py load_land.")
    on_land = Func(F("geom"), template=_ON_LAND, output_field=BooleanField())
    applied.append(LAND_CHOICES[choice])
    return queryset.filter(on_land) if choice == "only" else queryset.exclude(on_land)


def filter_sightings(queryset, params):
    """Returns (queryset, applied, excluded_no_position)."""
    applied = []
    excluded_no_position = 0

    if params.get("include_non_animal") != "1":
        queryset = queryset.exclude(species__category=NON_ANIMAL)
    else:
        applied.append("including non-animal records")

    # The sighting's own research group. It is its effort's wherever it has
    # one, and this way the sightings with no effort are not lost.
    queryset = _filter_research_group(queryset, params, "research_group", applied)
    queryset = _filter_time(queryset, params, "sighting_date", applied)

    species = _ints(params, "species")
    if species:
        queryset = queryset.filter(species_id__in=species)
        applied.append("species" if len(species) == 1 else f"{len(species)} species")

    vessels = _ints(params, "vessel")
    if vessels:
        queryset = queryset.filter(vessel_id__in=vessels)
        applied.append("vessel" if len(vessels) == 1 else f"{len(vessels)} vessels")

    region = (params.get("region") or "").strip()
    if region:
        queryset = queryset.filter(daily_effort__region=region)
        applied.append(f"region {region}")

    queryset = _filter_sub_area(queryset, params, "daily_effort__sub_area", applied)
    queryset = _filter_project(queryset, params, "daily_effort__project_objective", applied)
    queryset = _filter_with_or_without(queryset, params, _SIGHTING_NAMED, applied)

    # These four describe the day rather than the sighting, so they reach a
    # sighting through its effort. Without them the panel could read 31,550
    # sightings across 1 effort, because the filter moved one count and not
    # the other.
    locality = (params.get("locality") or "").strip()
    if locality:
        queryset = queryset.filter(daily_effort__locality=locality)
        applied.append(f"locality {locality}")

    survey_type = (params.get("survey_type") or "").strip()
    if survey_type:
        queryset = queryset.filter(daily_effort__survey_type=survey_type)
        applied.append(f"survey type {survey_type}")

    crew = (params.get("crew") or "").strip()
    if crew:
        queryset = queryset.filter(daily_effort__personnel__icontains=crew)
        applied.append(f'crew containing "{crew}"')

    track = (params.get("track") or "").strip()
    if track:
        queryset, note = _filter_sighting_track_status(queryset, track)
        if note:
            applied.append(note)

    position_type = (params.get("position_type") or "").strip()
    if position_type:
        queryset = queryset.filter(position_type=position_type)
        applied.append(f"position {position_type}")

    uncertain = uncertain_choice(params)
    if uncertain == "only":
        queryset = queryset.filter(species_uncertain=True)
        applied.append("species uncertain only")
    elif uncertain == "exclude":
        # exclude() keeps the rows where the flag is null as well as false.
        queryset = queryset.exclude(species_uncertain=True)
        applied.append("species uncertain excluded")

    queryset = _filter_land(queryset, params, applied)

    area = parse_polygon(params.get("area"))
    if area:
        excluded_no_position = queryset.filter(geom__isnull=True).count()
        queryset = queryset.filter(geom__within=area)
        applied.append("inside the drawn area")

    return queryset, _describe(applied), excluded_no_position


def species_choices(include_non_animal=False, options=None):
    """Species for the picker, by group and most recorded first within each.
    `options` are the page's own (with counts for its query), if it has them."""
    from .services import filter_options

    return [
        s for s in (options or filter_options())["species"]
        if include_non_animal or s["category"] != NON_ANIMAL
    ]
