"""Sorting, paging and the filter dropdowns, shared by the list views.

Nothing here talks to a template. Views assemble everything a page needs so
that no template can trigger a query.
"""

import csv
import json
from pathlib import Path

from django.contrib.gis.geos import GEOSGeometry
from django.core.cache import cache
from django.core.paginator import Paginator

from . import sub_areas

PAGE_SIZES = [25, 50, 100, 200]
DEFAULT_PAGE_SIZE = 50


def apply_sort(queryset, request, allowed, default):
    """Sort by a request parameter, restricted to a known set of columns.

    `allowed` maps the name that appears in the URL to the ORM field, so a
    request can never order by an arbitrary expression. Returns the queryset
    along with the current key and direction for the column headers.
    """
    key = request.GET.get("sort") or default
    descending = key.startswith("-")
    bare = key.lstrip("-")

    if bare not in allowed:
        bare = default.lstrip("-")
        descending = default.startswith("-")

    field = allowed[bare]
    order = f"-{field}" if descending else field

    # A stable tiebreak, otherwise pagination can repeat or skip rows where
    # the sort column has duplicates.
    return queryset.order_by(order, "pk"), bare, descending


def paginate(request, queryset):
    try:
        size = int(request.GET.get("per_page", DEFAULT_PAGE_SIZE))
    except ValueError:
        size = DEFAULT_PAGE_SIZE
    if size not in PAGE_SIZES:
        size = DEFAULT_PAGE_SIZE

    paginator = Paginator(queryset, size)
    page = paginator.get_page(request.GET.get("page"))
    return page, size


def querystring(request, **overrides):
    """The current query string with some parameters replaced.

    Used by column headers and pagination links so that changing the sort
    does not silently drop the active filters. A value of None removes the
    parameter.
    """
    params = request.GET.copy()
    for key, value in overrides.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"


def parse_polygon(raw):
    """The area drawn on the map, as GeoJSON, ready for a spatial lookup.

    None when nothing was drawn. ValueError when something arrived that
    cannot be read, so the view says so rather than quietly returning
    everything.
    """
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("The area could not be read as GeoJSON.") from exc

    if data.get("type") == "Feature":
        data = data.get("geometry")
    if not data:
        raise ValueError("The area contains no geometry.")

    geom = GEOSGeometry(json.dumps(data), srid=4326)
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"The area must be a polygon, not a {geom.geom_type}.")
    return geom


# ---------------------------------------------------------------------------
# Filter dropdown options
#
# These are identical on every request and change only when the database is
# reloaded, so they are built once and cached rather than queried per page.
# ---------------------------------------------------------------------------

FILTER_OPTIONS_KEY = "survey:filter_options:v9"


def filter_options():
    options = cache.get(FILTER_OPTIONS_KEY)
    if options is None:
        options = _build_filter_options()
        cache.set(FILTER_OPTIONS_KEY, options, 60 * 60)
    return options


# ---------------------------------------------------------------------------
# Counts that follow the query
#
# The cached options above carry ids, labels and colours, which never change
# between requests. The number beside each option does: it is what the picker
# would show with its own choice removed and every other filter kept. These
# are worked out per query and cached by the filter string.
# ---------------------------------------------------------------------------

FACET_COUNTS_KEY = "survey:facet_counts:v2"
FACET_COUNTS_SECONDS = 5 * 60

# (facet, the parameter it ignores, the model field it groups by)
# Species count sightings. Every other picker counts efforts, on every page,
# so the numbers beside them can be read against the page's effort total.
_SIGHTING_FACETS = (("species", "species", "species_id"),)
_EFFORT_FACETS = (("research_group", "research_group", "research_group"),
                  ("sub_area", "sub_area", "sub_area"),
                  ("project", "project_objective", "project_objective"),
                  ("vessel", "vessel", "vessel_id"))


def _facet_counts(params, page):
    """{facet: {value: count}}. Each facet counts the records left by every
    filter except its own, so a picked species still shows how many of every
    other species match."""
    from django.db.models import Count

    from .export_stack import filter_string
    from .filters import ALL_RESEARCH_GROUPS, filter_efforts, filter_sightings
    from .models import DailyEffort, Sighting

    plan = [] if page == "efforts" else [(Sighting, filter_sightings, f) for f in _SIGHTING_FACETS]
    plan += [(DailyEffort, filter_efforts, f) for f in _EFFORT_FACETS]

    # Facets whose reduced filters come out the same share one grouped query.
    queries = {}
    for model, apply, facet in plan:
        reduced = params.copy()
        reduced.pop(facet[1], None)
        if facet[0] == "research_group":
            # With the parameter gone the default (CRC) would apply again.
            reduced["research_group"] = ALL_RESEARCH_GROUPS
        key = (model, filter_string(reduced))
        queries.setdefault(key, (apply, reduced, []))[2].append(facet)

    found = {}
    for (model, _qs), (apply, reduced, facets) in queries.items():
        queryset, _applied, _excluded = apply(model.objects.all(), reduced)
        fields = [f[2] for f in facets]
        rows = (queryset.order_by().values_list(*fields).annotate(n=Count("id")))
        for facet in facets:
            found[facet[0]] = {}
        for *values, n in rows:
            for facet, value in zip(facets, values):
                if value is not None:
                    totals = found[facet[0]]
                    totals[value] = totals.get(value, 0) + n
    return found


def filter_options_for(params, page="explore"):
    """filter_options() with every count following the current filters, on a
    copy: the cached options are shared and must never be written to. `page`
    is "efforts" for the Efforts list, which has no species picker. If the filters cannot be read, the global counts stand
    (the view reports the problem itself)."""
    from .export_stack import filter_string

    base = filter_options()
    key = f"{FACET_COUNTS_KEY}:{page == 'efforts'}:{filter_string(params)}"
    counts = cache.get(key)
    if counts is None:
        try:
            counts = _facet_counts(params, page)
        except ValueError:
            return base
        cache.set(key, counts, FACET_COUNTS_SECONDS)

    options = dict(base)

    def efforts_by_name(facet):
        found = counts[facet]
        listed = [dict(o, efforts=found.get(o["id"], 0)) for o in base[facet_key[facet]]]
        return sorted(listed, key=lambda o: (-o["efforts"], o["label"].lower()))

    facet_key = {"research_group": "research_groups", "project": "projects"}
    for facet, name in facet_key.items():
        options[name] = efforts_by_name(facet)

    by_value = counts["sub_area"]
    known = base["sub_area_values"]
    options["sub_areas"] = [
        dict(a, efforts=sum(by_value.get(v, 0) for v in sub_areas.matching_values(a["id"], known)))
        for a in base["sub_areas"]
    ]

    found = counts["vessel"]
    options["vessels"] = sorted(
        (dict(v, efforts=found.get(v["id"], 0)) for v in base["vessels"]),
        key=lambda v: (-v["efforts"], v["label"].lower()))

    if page != "efforts":
        found = counts["species"]
        order = list(SPECIES_GROUPS)
        species = sorted(
            (dict(s, count=found.get(s["id"], 0)) for s in base["species"]),
            key=lambda s: (order.index(s["group"]), -s["count"], s["label"].lower()))
        options["species"] = species
        options["species_groups"] = [
            dict(g, count=sum(s["count"] for s in species if s["group"] == g["key"]))
            for g in base["species_groups"]
        ]
    return options


# Species are grouped under these headings, in this order. The group is worked
# out from the name because the database only knows cetacean / pinniped /
# other. Each group has a hue and each species a shade of it, used on the map,
# its legend, the results list and the filter tags alike.
SPECIES_GROUPS = {
    "whale": "Whales",
    "dolphin": "Dolphins",
    "porpoise": "Porpoises",
    "orca": "Killer Whales",
    "sea_lion": "Sea Lions",
    "seal": "Seals",
    "otter": "Sea Otters",
    "turtle": "Sea Turtles",
    "unknown": "Unidentified",
    "other": "Not an animal",
}
GROUP_HUES = {
    "whale": 212, "dolphin": 188, "porpoise": 158, "orca": 262,
    "sea_lion": 16, "seal": 40, "otter": 330, "turtle": 95,
    "unknown": None, "other": None,   # grey, tinted toward the sea
}


# Two colour profiles, chosen on the Settings page and kept in a cookie.
# Cascadia is Cascadia's own palette, one colour per species code, from
# species_colours.csv; codes it does not list are drawn grey. Generic is the
# group shading above.
COLOUR_PROFILES = ("cascadia", "generic")
COLOUR_PROFILE_COOKIE = "colour_profile"
CASCADIA_UNLISTED = "#a7b0b6"
CASCADIA_CODE_ALIASES = {"Zica": "Zc"}   # the file's code for Cuvier's beaked whale


def colour_profile(request):
    value = request.COOKIES.get(COLOUR_PROFILE_COOKIE)
    return value if value in COLOUR_PROFILES else COLOUR_PROFILES[0]


def _cascadia_colours():
    path = Path(__file__).with_name("species_colours.csv")
    with open(path, newline="", encoding="utf-8") as handle:
        return {
            CASCADIA_CODE_ALIASES.get(row["Code"], row["Code"]):
                "#%02x%02x%02x" % tuple(int(v) for v in row["Color_rgb"].split(","))
            for row in csv.DictReader(handle)
        }


def _shade(group, index):
    """The group's hue, darkest for its most recorded species and lighter
    down the list, levelling off after six so rare species stay visible."""
    import colorsys

    hue = GROUP_HUES[group]
    light = 0.34 + min(index, 5) * 0.075
    # Rich enough to tell apart, soft enough to sit with the sea palette. The
    # grey groups carry a trace of the sea hue, as the page's greys do.
    hue, sat = (200, 0.12) if hue is None else (hue, 0.55)
    r, g, b = colorsys.hls_to_rgb(hue / 360, light, sat)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def species_group(species):
    name = (species.common_name or "").lower()
    if species.category == "non_animal":
        return "other"
    if species.category == "unidentified" or not name:
        return "unknown"
    if "killer whale" in name and "false" not in name:
        return "orca"
    if "sea lion" in name:
        return "sea_lion"
    if "seal" in name:
        return "seal"
    if "otter" in name:
        return "otter"
    if "turtle" in name:
        return "turtle"
    if "porpoise" in name:
        return "porpoise"
    if "dolphin" in name:
        return "dolphin"
    return "whale"


def _vessel_choices(sighting_counts, effort_counts):
    """Vessels for a dropdown, busiest first, with same-named boats told apart.

    Several names appear on more than one vessel row: there are three
    Musculus records with different codes. Showing the name three times
    would make the list unusable, so the code is appended wherever a name
    is not unique. Vessels with no name already show their code.
    """
    from collections import Counter

    from .models import Vessel

    vessels = list(Vessel.objects.all())
    duplicates = {
        name for name, n in Counter(v.label for v in vessels).items() if n > 1
    }

    choices = [
        {
            "id": v.id,
            "label": f"{v.label} ({v.code})" if v.label in duplicates else v.label,
            "sightings": sighting_counts.get(v.id, 0),
            "efforts": effort_counts.get(v.id, 0),
        }
        for v in vessels
    ]
    # Most used first. Ties fall back to the name so the order is stable.
    return sorted(
        choices, key=lambda c: (-c["sightings"], -c["efforts"], c["label"].lower())
    )


def _build_filter_options():
    from django.db.models import Count, Max, Min

    from .filters import MONTH_NAMES
    from .models import DailyEffort, Sighting, Species, Track

    def counts(model, field):
        return dict(
            model.objects.order_by()
            .exclude(**{f"{field}__isnull": True})
            .values_list(field)
            .annotate(n=Count("id"))
        )

    species_counts = counts(Sighting, "species_id")
    species = sorted(
        (
            {
                "id": s.id,
                "label": str(s),
                "category": s.category,
                "group": species_group(s),
                "group_label": SPECIES_GROUPS[species_group(s)],
                "count": species_counts.get(s.id, 0),
                "authoritative": s.name_is_authoritative,
            }
            for s in Species.objects.all()
        ),
        # By group, then most recorded first within each group.
        key=lambda s: (
            list(SPECIES_GROUPS).index(s["group"]), -s["count"], s["label"].lower()
        ),
    )
    cascadia = _cascadia_colours()
    codes = dict(Species.objects.values_list("id", "code"))
    rank = {}
    for sp in species:
        sp["cascadia_colour"] = cascadia.get(codes[sp["id"]], CASCADIA_UNLISTED)
        sp["colour"] = _shade(sp["group"], rank.setdefault(sp["group"], 0))
        rank[sp["group"]] += 1
    groups = [
        {"key": key, "label": label, "colour": _shade(key, 1),
         "count": sum(sp["count"] for sp in species if sp["group"] == key)}
        for key, label in SPECIES_GROUPS.items()
    ]
    by_key = {g["key"]: g for g in groups}
    for sp in species:
        sp["group_colour"] = by_key[sp["group"]]["colour"]

    vessels = _vessel_choices(
        counts(Sighting, "vessel_id"), counts(DailyEffort, "vessel_id")
    )

    def distinct(model, field):
        # order_by() clears Meta.ordering first. Django adds ordering
        # columns to the SELECT, and with them in place DISTINCT compares
        # those too, so every locality would come back once per date.
        return sorted(
            v
            for v in model.objects.order_by().values_list(field, flat=True).distinct()
            if v
        )

    sub_area_values = distinct(DailyEffort, "sub_area")
    main_sub_areas, other_sub_areas = sub_areas.choices(sub_area_values)
    efforts_by_sub_area = counts(DailyEffort, "sub_area")

    def sub_area_choice(name):
        n = sum(efforts_by_sub_area.get(v, 0)
                for v in sub_areas.matching_values(name, sub_area_values))
        return {"id": name, "label": name, "efforts": n}

    def by_effort_count(field, also=()):
        """Each value with its Effort count, most Efforts first. `also` adds
        values no effort has (research groups only on sightings), at 0."""
        found = counts(DailyEffort, field)
        found.update({v: 0 for v in also if v and v not in found})
        return [{"id": v, "label": v, "efforts": n}
                for v, n in sorted(found.items(), key=lambda kv: (-kv[1], kv[0].lower()))]

    span = DailyEffort.objects.aggregate(lo=Min("effort_date"), hi=Max("effort_date"))
    years = list(range(span["lo"].year, span["hi"].year + 1))

    return {
        "species": species,
        "species_groups": groups,
        "vessels": vessels,
        "regions": distinct(DailyEffort, "region"),
        "localities": distinct(DailyEffort, "locality"),
        # North to south, those with 250 or more efforts first (sub_areas.py).
        "sub_areas": [sub_area_choice(a) for a in main_sub_areas + other_sub_areas],
        "sub_area_values": sub_area_values,
        # Every research group, busiest first. 642 of the 1,019 have one
        # effort, so the picker is searched rather than scrolled.
        "research_groups": by_effort_count(
            "research_group", also=distinct(Sighting, "research_group")),
        "projects": by_effort_count("project_objective"),
        "survey_types": distinct(DailyEffort, "survey_type"),
        "position_types": distinct(Sighting, "position_type"),
        "sight_types": distinct(Sighting, "sight_type"),
        "years": years,
        "months": [(str(n), name) for n, name in enumerate(MONTH_NAMES, 1)],
        # Meteorological seasons, as the National Weather Service uses them
        # for the Pacific Northwest.
        "seasons": [("Winter", "12,1,2"), ("Spring", "3,4,5"),
                    ("Summer", "6,7,8"), ("Fall", "9,10,11")],
        "date_min": span["lo"],
        "date_max": span["hi"],
    }


def species_colour(species_id, profile="cascadia"):
    """The species' colour on every map, list and tag, in the given profile."""
    key = "colour" if profile == "generic" else "cascadia_colour"
    for s in filter_options()["species"]:
        if s["id"] == species_id:
            return s[key]
    return "#5d6e77"
