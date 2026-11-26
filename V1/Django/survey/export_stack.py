"""The queries waiting to be exported, kept in the session.

The stack holds each query's filters, never its rows: a kind, the query string
the page was showing, and a label. The sheets are worked out from the current
database when the file is made, so a download always matches what the site
holds now, and a session that outlives a data fix does not export old values.

An Effort or Sighting page adds that one record, so those two kinds carry the
record's number instead of filters.

A query of Efforts can also bring in the Sightings of those Efforts, and a
query of Sightings the Efforts of those Sightings. That is a choice kept with
each query, on by default, so one query can bring its related records and
another not. An Explore query already gives both, so it has no such choice.
"""

from django.http import QueryDict

from .filters import (MONTH_NAMES, filter_efforts, filter_sightings,
                      match_sightings_ticked, research_group_choice,
                      sighting_filter_active, uncertain_choice)
from .models import DailyEffort, Sighting, Species, Vessel

KEY = "export_stack"
LAND_TEXT = {"exclude": "Not On Land", "only": "Only On Land"}
MAX_QUERIES = 20

# What each kind of query contributes: (Efforts, Sightings). Explore gives
# both, the way its page lists both.
KINDS = {
    "explore": (True, True),
    "efforts": (True, False),
    "sightings": (False, True),
    "effort": (True, False),
    "sighting": (False, True),
}
ONE_RECORD = ("effort", "sighting")
# The kinds that can bring in their related records, and what they bring.
RELATED = {"efforts": "sightings", "effort": "sightings",
           "sightings": "efforts", "sighting": "efforts"}
RELATED_LABELS = {"sightings": "Include The Sightings Of These Efforts",
                  "efforts": "Include The Efforts Of These Sightings"}
KIND_LABELS = {"explore": "Explore", "efforts": "Efforts", "sightings": "Sightings",
               "effort": "Effort", "sighting": "Sighting"}

# How a page was left, not what it was filtering: paging and sorting, which
# filter sections were open, and the Explore map's view and layers.
NOT_A_FILTER = {"page", "per_page", "sort", "open", "view", "base", "labels",
                "tracks", "points", "clusters"}


class ExportError(ValueError):
    """A query that cannot be read. The message says why, in plain words."""


def filter_string(params):
    """The filters in a query string, without the page's own state.

    Every value is kept, not just the last: species, vessel and month repeat.
    """
    kept = QueryDict(mutable=True)
    for name in params:
        if name in NOT_A_FILTER:
            continue
        values = [v for v in params.getlist(name) if v]
        if values:
            kept.setlist(name, values)
    return kept.urlencode()


# ---------------------------------------------------------------------------
# The stack
# ---------------------------------------------------------------------------


def load(request):
    """The stack as stored. An entry that is not a known kind is left out."""
    stored = request.session.get(KEY) or []
    return [e for e in stored if isinstance(e, dict) and e.get("kind") in KINDS]


def count(request):
    return len(load(request))


def _save(request, stack):
    # Sessions are database rows, so only a change is worth a write.
    if request.session.get(KEY) != stack:
        request.session[KEY] = stack


def brings_related(entry):
    """Whether a query adds the records related to the ones it selects. An
    entry from before the choice existed brings them, the way a new one does."""
    return entry["kind"] in RELATED and entry.get("related", True)


def add(request, kind, qs, related=True):
    """Put a query on the stack. Returns (entry, added): added is False when
    the same query was already there."""
    if kind not in KINDS:
        raise ExportError("That is not something that can be exported.")
    qs = _one_record(qs) if kind in ONE_RECORD else filter_string(QueryDict(qs))
    stack = load(request)
    for entry in stack:
        if entry["kind"] == kind and entry["qs"] == qs:
            return entry, False
    if len(stack) >= MAX_QUERIES:
        raise ExportError(f"An export holds at most {MAX_QUERIES} queries. "
                          "Remove one before adding another.")
    entry = {"kind": kind, "qs": qs, "label": label(kind, qs)}
    if kind in RELATED:
        entry["related"] = bool(related)
    resolve(entry)   # a query that cannot be read is refused now, not at download
    _save(request, stack + [entry])
    return entry, True


def remove(request, index):
    stack = load(request)
    if 0 <= index < len(stack):
        del stack[index]
        _save(request, stack)
        return True
    return False


def set_related(request, index, related):
    """Turn a query's related records on or off. Returns False when there is
    no such query, or it has no such choice."""
    stack = load(request)
    if not 0 <= index < len(stack) or stack[index]["kind"] not in RELATED:
        return False
    stack[index] = {**stack[index], "related": bool(related)}
    _save(request, stack)
    return True


def _one_record(qs):
    number = QueryDict(qs).get("id", "")
    if not number.isdigit():
        raise ExportError("That record could not be found.")
    return f"id={int(number)}"


# ---------------------------------------------------------------------------
# What a query selects
# ---------------------------------------------------------------------------


def resolve(entry):
    """(Efforts, Sightings) for one query: a queryset each, or None where the
    query gives none of that kind. Raises ExportError if it cannot be read.

    Where the query brings its related records, the other kind is those of the
    records it selected: every Sighting of the Efforts, or every Effort of the
    Sightings, whatever the filters say, as the Effort and Sighting pages show.
    """
    kind, params = entry["kind"], QueryDict(entry["qs"])
    wants_efforts, wants_sightings = KINDS[kind]
    efforts = sightings = None
    try:
        if kind in ONE_RECORD:
            # One record is that record, whatever the Research Group filter says.
            number = int(params["id"])
            if kind == "effort":
                efforts = DailyEffort.objects.filter(legacy_daily_effort_id=number)
            else:
                sightings = Sighting.objects.filter(legacy_sighting_id=number)
            found = efforts if efforts is not None else sightings
            if not found.exists():
                raise ExportError(f"{KIND_LABELS[kind]} {number} could not be found.")
        else:
            if wants_efforts:
                efforts = filter_efforts(DailyEffort.objects.all(), params)[0]
            if wants_sightings:
                sightings = filter_sightings(Sighting.objects.all(), params)[0]
    except (ValueError, KeyError) as exc:
        if isinstance(exc, ExportError):
            raise
        raise ExportError(f"The filters for {entry.get('label') or KIND_LABELS[kind]} "
                          f"could not be used: {exc}")
    if brings_related(entry):
        if efforts is not None:
            sightings = Sighting.objects.filter(daily_effort__in=efforts.order_by().values("pk"))
        else:
            efforts = DailyEffort.objects.filter(pk__in=sightings.order_by().values("daily_effort_id"))
    return efforts, sightings


# ---------------------------------------------------------------------------
# What a query is called
# ---------------------------------------------------------------------------


def _runs(numbers, name):
    """Sorted numbers as runs: 2014 to 2016, 2019."""
    runs = []
    for n in sorted(numbers):
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    return ", ".join(name(a) if a == b else f"{name(a)} to {name(b)}" for a, b in runs)


def _numbers(params, name, low, high):
    return {int(v) for v in params.getlist(name) if v.isdigit() and low <= int(v) <= high}


def _few(names, limit=3):
    return ", ".join(names[:limit]) + (f" and {len(names) - limit} more" if len(names) > limit else "")


def label(kind, qs):
    """A query in words, such as Explore: Tursiops truncatus, CRC, 2024."""
    params = QueryDict(qs)
    if kind in ONE_RECORD:
        return f"{KIND_LABELS[kind]} {params.get('id')}"

    parts = []
    species = _numbers(params, "species", 1, 2 ** 31)
    if species and KINDS[kind][1]:
        found = Species.objects.filter(id__in=species)
        parts.append(_few(sorted(s.scientific_name or str(s) for s in found)))

    choice = research_group_choice(params)
    parts.append(choice["label"].replace(" (Default)", ""))

    start, end = params.get("date_from"), params.get("date_to")
    if start or end:
        parts.append(f"{start} to {end}" if start and end else f"from {start}" if start else f"to {end}")
    years = _numbers(params, "year", 1900, 2200)
    if years:
        parts.append(_runs(years, str))
    months = _numbers(params, "month", 1, 12)
    if 0 < len(months) < 12:
        parts.append(_runs(months, lambda m: MONTH_NAMES[m - 1]))

    vessels = _numbers(params, "vessel", 1, 2 ** 31)
    if vessels:
        parts.append("Vessel " + _few(sorted(Vessel.objects.filter(id__in=vessels).values_list("code", flat=True))))
    for name, text in (("region", "{}"), ("sub_area", "{}"), ("locality", "{}"),
                       ("survey_type", "{}"), ("project_objective", "{}"), ("crew", 'Crew "{}"')):
        values = [v.strip() for v in params.getlist(name) if v.strip()]
        if values:
            parts.append(text.format(_few(values)))
    for name, text in (("tags", "Tags"), ("samples", "Samples")):
        if params.get(name) in ("with", "without"):
            parts.append(f"{params.get(name).title()} {text}")
    tracks = {"none": "No Track File", "any": "Has A Track Record", "available": "Track File Available",
              "missing_file": "Track File Missing"}
    if params.get("track") in tracks:
        parts.append(tracks[params.get("track")])
    if params.get("position_type"):
        parts.append(f"Position {params.get('position_type')}")
    uncertain = uncertain_choice(params)
    if uncertain:
        parts.append("Species Uncertain Only" if uncertain == "only" else "Species Uncertain Excluded")
    if params.get("land") in LAND_TEXT:
        parts.append(LAND_TEXT[params.get("land")])
    if params.get("include_non_animal") == "1":
        parts.append("Including Non-Animal Records")
    if not match_sightings_ticked(params) and sighting_filter_active(params):
        parts.append("All Efforts")
    if params.get("area"):
        parts.append("Drawn Area")

    text = f"{KIND_LABELS[kind]}: " + ", ".join(parts)
    return text if len(text) <= 160 else text[:157] + "..."
