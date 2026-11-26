"""
The GPS track files: what is wrong with them, and putting it right.

A track record is fine when it is linked to an effort and its file is in
object storage. Everything else is one of four problems, and each is worked
out from those two facts rather than from the stored status, which an older
tool could leave behind (eleven records were linked without it being
updated):

    no_track      an effort has no track record at all
    missing_file  an effort's track record names a file storage does not hold
    unlinked      a file is in storage but linked to no effort
    lost          a record names a file, but the file is not in storage and
                  no effort is linked: DB167's track table had the name typed
                  in, and nothing else

Every fix goes through the audit log, under the name of whoever made it, and
can be undone from there. Linking and unlinking are here; uploading a file is
gps/tracks.add(), the same code that regenerates every track's line.
"""

from django.db.models import Exists, OuterRef, Q

from survey.models import DailyEffort, Track

from . import audit

HAS_FILE = ("available", "unassociated")

PROBLEMS = {
    "no_track": ("No track file", "The effort has no GPS track file at all."),
    "missing_file": ("File missing", "The effort names a track file that isn't in storage."),
    "unlinked": ("Unlinked file", "A track file is in storage but isn't linked to an effort."),
    "lost": ("Lost file", "A track record names a file that isn't in storage, "
                          "and isn't linked to an effort."),
}


def problem_of(track):
    """Which problem one track record has, or None when it is fine."""
    linked = track.daily_effort_id is not None
    has_file = track.track_status in HAS_FILE
    if linked and has_file:
        return None
    if linked:
        return "missing_file"
    return "unlinked" if has_file else "lost"


def efforts_without_track():
    return DailyEffort.objects.filter(~Exists(Track.objects.filter(daily_effort=OuterRef("pk"))))


def tracks_with(problem):
    linked = Q(daily_effort__isnull=False)
    has_file = Q(track_status__in=HAS_FILE)
    return Track.objects.filter({
        "missing_file": linked & ~has_file,
        "unlinked": ~linked & has_file,
        "lost": ~linked & ~has_file,
    }[problem])


def counts():
    return {
        "no_track": efforts_without_track().count(),
        "missing_file": tracks_with("missing_file").count(),
        "unlinked": tracks_with("unlinked").count(),
        "lost": tracks_with("lost").count(),
    }


def efforts_on(day, exclude=None):
    """The efforts recorded on one day: a file's potential matches."""
    if not day:
        return []
    found = DailyEffort.objects.filter(effort_date=day).select_related("vessel")
    if exclude:
        found = found.exclude(pk=exclude)
    return list(found.order_by("legacy_daily_effort_id"))


def files_on(day):
    """Unlinked files recorded on one day: an effort's potential matches."""
    if not day:
        return []
    return list(tracks_with("unlinked").filter(survey_date=day)
                .select_related("vessel").order_by("object_key"))


# Fixes. Each returns a sentence saying what happened, or raises ValueError
# with one saying why it could not.


def link(actor, track, effort):
    """Link a track record to an effort. With its file there, it is complete."""
    if track.daily_effort_id == effort.pk:
        raise ValueError(f"{track.object_key} is already linked to effort "
                         f"{effort.legacy_daily_effort_id}.")
    has_file = track.track_status in HAS_FILE
    audit.update(actor, "track", track.legacy_track_id,
                 {"EffortID": effort.legacy_daily_effort_id,
                  "track_status": "available" if has_file else "missing_file"},
                 action="associate",
                 comment=f"Linked {track.object_key} to effort "
                         f"{effort.legacy_daily_effort_id}.")
    return f"{track.object_key} linked to effort {effort.legacy_daily_effort_id}."


def unlink(actor, track):
    """Undo a link made in error; the file stays in storage."""
    if track.daily_effort_id is None:
        raise ValueError(f"{track.object_key} is not linked to an effort.")
    number = track.daily_effort.legacy_daily_effort_id
    has_file = track.track_status in HAS_FILE
    audit.update(actor, "track", track.legacy_track_id,
                 {"EffortID": None,
                  "track_status": "unassociated" if has_file else "unresolved"},
                 action="dissociate",
                 comment=f"Unlinked {track.object_key} from effort {number}.")
    return f"{track.object_key} is no longer linked to effort {number}."
