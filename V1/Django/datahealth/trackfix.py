"""
The GPS track files: which Effort each belongs to, and what the Track File
Manager lists.

A track file is shown as one of three kinds, worked out from the two facts that matter,
whether it is matched to an Effort and whether its file has any points (the
stored status can lag behind both, which is why the page is not built from it):

    matched       matched to an Effort, and the file has points
    blank         the file has no points yet; matched or not
    unmatched     the file has points, and no Effort has it

An Effort has one track file at most. Nothing may give an Effort a second one:
matching a file, importing one with a match and adding one for an Effort all
come through check_room(). The 31 Efforts that already had two or three
(ETL/dbt/seeds/multi_track_efforts.csv) keep them, and may have them edited,
unmatched or deleted, but they cannot gain another, because they have a track
already. The pipeline fails its build if any other Effort has more than one.

Changing an Effort's track file is two fixes in one step: the old file is
unmatched (it stays in storage) and the chosen one is matched, each its own
audit entry and each undone on its own.

Every fix goes through the audit log, under the name of whoever made it, and
can be undone from there. Matching and unmatching are here; uploading, saving
and deleting a file are gps/tracks.py, the same code that regenerates every
track's line.
"""

from django.db import connection, transaction
from django.db.models import Case, Count, F, IntegerField, Q, TextField, Value, When
from django.db.models.functions import Cast

from survey import track_checks
from survey.models import DailyEffort, EffortTimeline, Track

from . import audit

# The statuses of a record whose file has points. A blank file is stored too,
# but it is the file with nothing in it, so it is not counted here.
HAS_FILE = ("available", "unassociated")


def state_of(track):
    """matched, unmatched or blank: the three a file is shown as."""
    if not track.point_count:
        return "blank"
    return "matched" if track.daily_effort_id is not None else "unmatched"


# What the explorer lists


def files(params, offset=0, limit=100):
    """
    One page of the explorer's list, newest first, and how many files match.

    `params` are the filters: q (part of the file name), status (matched,
    unmatched or blank), vessel (its code), year, and health: "good" for the
    files whose checks found nothing (survey/track_checks.py), or a problem's
    code for the files with that problem. Every file with a name is listed,
    matched or not.
    """
    found = Track.objects.filter(object_key__isnull=False).exclude(object_key="")
    health = params.get("health")
    if health:
        checked = track_checks.problems(good=True)
        found = found.filter(object_key__in=[k for k, codes in checked.items()
                                             if (codes == [] if health == "good" else health in codes)])
    q = (params.get("q") or "").strip()
    if q:
        found = found.filter(object_key__icontains=q)
    status = params.get("status")
    if status == "blank":
        found = found.filter(Q(point_count__isnull=True) | Q(point_count=0))
    elif status == "matched":
        found = found.filter(point_count__gt=0, daily_effort__isnull=False)
    elif status == "unmatched":
        found = found.filter(point_count__gt=0, daily_effort__isnull=True)
    if params.get("vessel"):
        found = found.filter(vessel__code=params["vessel"])
    year = params.get("year")
    if year and year.isdigit():
        found = found.filter(survey_date__year=int(year))
    total = found.count()
    rows = (found.select_related("vessel")
            .order_by(F("survey_date").desc(nulls_last=True), "-legacy_track_id")[offset:offset + limit])
    return [{"id": t.legacy_track_id, "name": t.object_key,
             "date": t.survey_date.isoformat() if t.survey_date else None,
             "vessel": t.vessel.code if t.vessel else None, "state": state_of(t)}
            for t in rows], total


def facets():
    """The vessel codes and years the explorer's filters offer."""
    vessels = (Track.objects.filter(vessel__isnull=False).order_by("vessel__code")
               .values_list("vessel__code", flat=True).distinct())
    years = (Track.objects.filter(survey_date__isnull=False).order_by("-survey_date__year")
             .values_list("survey_date__year", flat=True).distinct())
    return list(vessels), list(years)


def deleted_files(params):
    """Tracks deleted and not restored, from the audit log: [{id, name, ...}].
    They are not in the database, so the explorer's other filters do not
    apply, only the name search."""
    q = (params.get("q") or "").strip().lower()
    out = []
    for entry in audit.deleted("TrackT"):
        row = (entry["snapshot"].get("TrackT") or [{}])[0]
        name = row.get("file_name") or row.get("TrackFileName")
        if not name or (q and q not in name.lower()):
            continue
        out.append({"id": int(entry["pk"]), "name": name, "date": row.get("SurveyDate"),
                    "vessel": row.get("Vessel"), "state": "deleted", "entry": entry["id"]})
    return out


# Efforts with no track file, from their recorded positions

POSITIONS_CAP = 200


def positioned(rows=None):
    """The timeline rows that can be a point in a file: a time and a position."""
    return (rows if rows is not None else EffortTimeline.objects).filter(
        at__isnull=False, lat__isnull=False, lon__isnull=False)


def timeline_events(effort):
    """What was recorded during an Effort that has a position (weather readings, log
    entries, sightings), in time order, for the Track File Manager's map. Times as the
    Effort page shows them."""
    from django.template.defaultfilters import time as as_time

    if effort is None:
        return []
    return [{"kind": r.kind, "id": r.legacy_id, "at": as_time(r.at, "H:i") or None,
             "label": r.label, "lat": float(r.lat), "lon": float(r.lon), "url": r.url}
            for r in positioned(effort.timeline).order_by("at", "row_key")]


def position_rows(effort):
    """[(time, latitude, longitude)] in time order for one Effort, as the
    Effort's page draws its dashed line."""
    return list(positioned(effort.timeline).order_by("at", "row_key").values_list("at", "lat", "lon"))


def position_efforts(params, limit=POSITIONS_CAP):
    """
    The Efforts that have no track file and at least two recorded positions
    (log entries, weather readings, sightings), newest first, and how many
    there are in all. `params` has q: words that each must be in the date, the
    vessel's code or name, or the research group. There are about 17,000, so
    only the first `limit` are returned.
    """
    enough = (positioned().order_by().values("daily_effort").annotate(n=Count("row_key"))
              .filter(n__gte=2).values("daily_effort"))
    found = DailyEffort.objects.filter(tracks__isnull=True, effort_date__isnull=False, pk__in=enough)
    words = (params.get("q") or "").split()
    if words:
        found = found.annotate(day=Cast("effort_date", TextField()))
    for word in words:
        found = found.filter(Q(day__icontains=word) | Q(vessel__code__icontains=word)
                             | Q(vessel__name__icontains=word) | Q(research_group__icontains=word))
    total = found.count()
    rows = found.select_related("vessel").order_by("-effort_date", "-legacy_daily_effort_id")[:limit]
    return [{"id": e.legacy_daily_effort_id, "date": e.effort_date.isoformat(),
             "vessel": e.vessel.code if e.vessel else None, "group": e.research_group,
             "name": " ".join(filter(None, [e.effort_date.isoformat(), e.vessel.code if e.vessel else None,
                                            e.research_group])) + f" (Effort {e.legacy_daily_effort_id})",
             "state": "draft"} for e in rows], total


# Matching


def efforts_on(day, group=None):
    """
    The Efforts recorded on one day, for the picker: each with whether it has a
    track file already, because an Effort has one at most.
    """
    if not day:
        return []
    found = (DailyEffort.objects.filter(effort_date=day).select_related("vessel")
             .annotate(tracks_held=Count("tracks")))
    if group:
        found = found.filter(research_group=group)
    return [{"id": e.legacy_daily_effort_id, "vessel": e.vessel.code if e.vessel else None,
             "locality": e.locality, "group": e.research_group, "taken": e.tracks_held > 0}
            for e in found.order_by("vessel__code", "legacy_daily_effort_id")]


def suggest(date, vessel):
    """
    The Effort a file most likely belongs to, for the Import Files pop-up:
    among the CRC Efforts on its date that have no track file, the one on the
    vessel its name gives, else the only one. None when there is no such Effort.
    """
    free = [e for e in efforts_on(date, "CRC") if not e["taken"]]
    for e in free:
        if vessel and e["vessel"] and e["vessel"].upper() == vessel.upper():
            return e["id"]
    return free[0]["id"] if len(free) == 1 else None


def check_room(effort):
    """Raise ValueError unless the Effort has no track file yet."""
    if Track.objects.filter(daily_effort=effort).exists():
        raise ValueError(f"Effort {effort.legacy_daily_effort_id} already has a track file, so "
                         "another cannot be added. An Effort has one track file at most.")


def allowed_tracks(effort):
    """How many track files an Effort may have: one, or the number it had before
    the rule, for the Efforts the pipeline's seed lists (multi_track_efforts)."""
    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass('build.multi_track_efforts') IS NOT NULL")
        if cur.fetchone()[0]:
            cur.execute("SELECT tracks FROM build.multi_track_efforts WHERE effort = %s",
                        [effort.legacy_daily_effort_id])
            row = cur.fetchone()
            if row:
                return row[0]
    return 1


def check_put_back(effort_id, track_id):
    """
    Raise ValueError if putting a track back on an Effort, by undoing or
    restoring a change, would give it more than it may have: another file was
    matched to it since. `effort_id` is the Effort's hashed Primary Key.
    """
    effort = DailyEffort.objects.filter(pk=effort_id).first()
    if effort is None:
        return
    others = Track.objects.filter(daily_effort=effort).exclude(legacy_track_id=track_id).count()
    if others + 1 > allowed_tracks(effort):
        raise ValueError(f"Effort {effort.legacy_daily_effort_id} has another track file now, and an "
                         "Effort has one track file at most, so this cannot be put back. Remove the "
                         "other file's match first.")


# Fixes. Each returns a sentence saying what happened, or raises ValueError
# with one saying why it could not.


def link(actor, track, effort):
    """Match a track record to an Effort. It must have no track file already."""
    if track.daily_effort_id == effort.pk:
        raise ValueError(f"{track.object_key} is already matched to effort "
                         f"{effort.legacy_daily_effort_id}.")
    check_room(effort)
    return _match(actor, track, effort)


def _match(actor, track, effort):
    """The match itself, once the Effort is known to have room."""
    # daily_effort_id is the effort's hashed Primary Key, so the match holds
    # however DB167 renumbers the effort; EffortID is DB167's ID, as a value.
    audit.update(actor, "track", track.legacy_track_id,
                 {"EffortID": effort.legacy_daily_effort_id, "daily_effort_id": effort.pk,
                  "track_status": "available" if track.point_count else "blank"},
                 action="associate",
                 comment=f"Matched {track.object_key} to effort "
                         f"{effort.legacy_daily_effort_id}.")
    return f"{track.object_key} matched to effort {effort.legacy_daily_effort_id}."


def unlink(actor, track):
    """Undo a match made in error; the file stays in storage."""
    if track.daily_effort_id is None:
        raise ValueError(f"{track.object_key} is not matched to an effort.")
    number = track.daily_effort.legacy_daily_effort_id
    audit.update(actor, "track", track.legacy_track_id,
                 {"EffortID": None, "daily_effort_id": None,
                  "track_status": "unassociated" if track.point_count is not None else "unresolved"},
                 action="dissociate",
                 comment=f"Unmatched {track.object_key} from effort {number}.")
    return f"{track.object_key} is no longer matched to effort {number}."


def candidates(effort, q="", all_dates=False, limit=300):
    """
    The track files an Effort could be given: those no Effort has, for the
    Change Track File pop-up. By default only those on the Effort's date and
    in its Research Group (a file imported without a match has no group, so it
    is offered too); `all_dates` offers the Research Group's files on any date;
    `q` is part of the file name. Those on the Effort's vessel come first.
    Returns (files, how many there are in all).
    """
    found = Track.objects.filter(daily_effort__isnull=True, object_key__isnull=False).exclude(object_key="")
    if effort.research_group:
        found = found.filter(Q(research_group=effort.research_group) | Q(research_group__isnull=True))
    if not all_dates and effort.effort_date:
        found = found.filter(survey_date=effort.effort_date)
    q = (q or "").strip()
    if q:
        found = found.filter(object_key__icontains=q)
    total = found.count()
    if effort.vessel_id:
        found = found.annotate(first=Case(When(vessel_id=effort.vessel_id, then=Value(0)),
                                          default=Value(1), output_field=IntegerField()))
    else:
        found = found.annotate(first=Value(1, output_field=IntegerField()))
    rows = found.select_related("vessel").order_by(
        "first", F("survey_date").desc(nulls_last=True), "object_key")[:limit]
    return [{"id": t.legacy_track_id, "name": t.object_key,
             "date": t.survey_date.isoformat() if t.survey_date else None,
             "vessel": t.vessel.code if t.vessel else None, "points": t.point_count or 0,
             "length_nm": float(t.length_nm) if t.length_nm is not None else None,
             "same_vessel": bool(effort.vessel_id and t.vessel_id == effort.vessel_id)}
            for t in rows], total


def change(actor, effort, new, old=None):
    """
    Give an Effort another track file: `old`, the file it has now, is unmatched
    (its file is kept) and `new`, a file no Effort has, is matched, as two
    audit entries made together, so either both happen or neither. With no
    `old`, the Effort has none, and `new` is matched alone. The rule that an
    Effort has one track file at most holds, and the 31 Efforts that have more
    keep the number they have: one of their files is swapped for another.
    """
    if not new.object_key:
        raise ValueError("That track record has no file to match.")
    if new.daily_effort_id is not None:
        raise ValueError(f"{new.object_key} is matched to an Effort already. Choose a file no Effort has.")
    if old is None:
        return link(actor, new, effort)
    if old.daily_effort_id != effort.pk:
        raise ValueError(f"{old.object_key} is no longer matched to effort {effort.legacy_daily_effort_id}. "
                         "Open the Effort again to see its track file now.")
    if old.pk == new.pk:
        raise ValueError("That is the track file the Effort has already.")
    with transaction.atomic():
        unlink(actor, old)
        # The Effort has room for the new file only if the swap leaves it no more than it may have.
        if Track.objects.filter(daily_effort=effort).count() + 1 > allowed_tracks(effort):
            raise ValueError(f"Effort {effort.legacy_daily_effort_id} has another track file now, and an "
                             "Effort has one track file at most. Nothing was changed.")
        _match(actor, new, effort)
    return (f"Effort {effort.legacy_daily_effort_id} now has {new.object_key}. {old.object_key} is no longer "
            "matched to an Effort, and its file is kept.")
