"""Turning request parameters into queryset filters.

Kept apart from the views because the list page, the Explore map and the
export all have to filter the same way. If they drifted, an export would not
match the list it came from.

Each function returns the filtered queryset plus a description of what was
applied, which the pages use to say what the reader is looking at.
"""

from .services import parse_polygon


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


def filter_efforts(queryset, params):
    """Narrow a queryset of efforts by the filters on the page.

    Returns (queryset, applied, excluded_no_position). The last is the number
    of efforts dropped purely for having no position when an area filter is
    active, which the page reports rather than letting them vanish.
    """
    applied = []
    excluded_no_position = 0

    queryset = _filter_time(queryset, params, "effort_date", applied)

    locality = (params.get("locality") or "").strip()
    if locality:
        queryset = queryset.filter(locality=locality)
        applied.append(f"locality {locality}")

    region = (params.get("region") or "").strip()
    if region:
        queryset = queryset.filter(region=region)
        applied.append(f"region {region}")

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

    queryset, track_note = _filter_effort_track_status(queryset, params.get("track"))
    if track_note:
        applied.append(track_note)

    area = parse_polygon(params.get("area"))
    if area:
        excluded_no_position = queryset.filter(start_point__isnull=True).count()
        queryset = queryset.filter(start_point__within=area)
        applied.append("inside the drawn area")

    return queryset, _describe(applied), excluded_no_position


def _filter_effort_track_status(queryset, value, via="tracks"):
    """
    The GPS track filter, in the admin Track files page's words.

    An effort is Available (a linked track whose file is in storage), File
    missing (a linked track whose file is not), or has No track file. The
    other two problems, Unlinked file and Lost file, belong to files that no
    effort points at, so they are not something an effort can be filtered by.
    Worked out from whether the file is in storage rather than the stored
    status alone, the same way the admin page does it.
    """
    from .models import Track
    has_file = {f"{via}__track_status__in": Track.HAS_FILE}
    if value == "none":
        return queryset.filter(**{f"{via}__isnull": True}), "with no track file"
    if value == "any":
        return queryset.filter(**{f"{via}__isnull": False}).distinct(), "with a track record"
    if value == "available":
        return queryset.filter(**has_file).distinct(), "with their track file"
    if value == "missing_file":
        return (queryset.filter(**{f"{via}__isnull": False}).exclude(**has_file).distinct(),
                "whose track file is missing")
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


def filter_sightings(queryset, params):
    """Returns (queryset, applied, excluded_no_position)."""
    applied = []
    excluded_no_position = 0

    if params.get("include_non_animal") != "1":
        queryset = queryset.exclude(species__category=NON_ANIMAL)
    else:
        applied.append("including non-animal records")

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

    if params.get("uncertain") == "1":
        queryset = queryset.filter(species_uncertain=True)
        applied.append("species uncertain only")

    area = parse_polygon(params.get("area"))
    if area:
        excluded_no_position = queryset.filter(geom__isnull=True).count()
        queryset = queryset.filter(geom__within=area)
        applied.append("inside the drawn area")

    return queryset, _describe(applied), excluded_no_position


def species_choices(include_non_animal=False):
    """Species for the picker, by group and most recorded first within each."""
    from .services import filter_options

    return [
        s for s in filter_options()["species"]
        if include_non_animal or s["category"] != NON_ANIMAL
    ]
