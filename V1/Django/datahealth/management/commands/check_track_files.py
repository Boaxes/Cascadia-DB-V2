"""
Check every GPS file in the bucket for data that is probably wrong, and write
what each check found to a JSON file of its own (survey/track_checks.py).

    python manage.py check_track_files            check what changed since the last run
    python manage.py check_track_files --all      check every file again
    python manage.py check_track_files --key K    only this file (repeat for more)

A file is checked again whenever it is written, so this is the safeguard: the
server runs it every night at 2am Pacific (ops/systemd/sedb-track-checks.timer).
It also removes the summaries of files no longer in the bucket. A file whose
bytes and rules are the same as at its last check would give the same answer,
so it is skipped unless --all is given. The bucket is only read.
"""

import time

from django.core.management.base import BaseCommand, CommandError

from datahealth import events
from survey import track_checks, track_objects


class Command(BaseCommand):
    help = "Check every GPS file for data that is probably wrong, one JSON summary each."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", dest="everything",
                            help="Check every file again, even those unchanged since their last check.")
        parser.add_argument("--key", action="append", dest="keys",
                            help="Only this file. Repeat for more than one.")

    def handle(self, everything=False, keys=None, **options):
        if not track_objects.can_write():
            raise CommandError("Reading the whole bucket needs SPACES_LOCAL_DIR, or SPACES_ENDPOINT, "
                               "SPACES_KEY and SPACES_SECRET.")
        self.stdout.write(f"Checks go to {track_checks.folder()}")
        if keys:
            for key in keys:
                body = track_objects.get(key)
                if body is None:
                    raise CommandError(f"{key} is not in the bucket.")
                found = track_checks.refresh(key, body)
                self.stdout.write(f"{key}: " + (", ".join(p["label"] for p in found["problems"]) or "no problems"))
            return
        started = time.monotonic()
        try:
            checked, unchanged, removed = track_checks.check_all(everything, report=self.stdout.write)
        except Exception as error:
            events.record("tracks", "nightly_check_failed", actor="Nightly Timer", message=f"{type(error).__name__}: {error}")
            raise
        flagged = len(track_checks.problems())
        events.record("tracks", "nightly_check", actor="Nightly Timer", all_files=everything, checked=checked,
                      unchanged=unchanged, removed=removed, with_problems=flagged,
                      seconds=round(time.monotonic() - started, 1),
                      message=f"Checked {checked:,} files, {unchanged:,} unchanged, {removed:,} old summaries "
                              f"removed. {flagged:,} files have a problem.")
        self.stdout.write(self.style.SUCCESS(
            f"Checked {checked:,} files, {unchanged:,} unchanged since their last check, "
            f"{removed:,} old summaries removed. {flagged:,} files have a problem."))
