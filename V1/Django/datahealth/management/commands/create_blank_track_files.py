"""
Give every track record a file in the bucket.

    python manage.py create_blank_track_files --dry-run     say which files would be made
    python manage.py create_blank_track_files               make them

DB167 holds only the names of track files, so some records name a file the
bucket does not have. For each of those this writes a blank one, the header
`datetime_utc,latitude,longitude` and nothing else, and a row in
app.track_geometry with no points. The Track File Manager can then open every
track, and Fill From File can fill a blank one. A file that is already in the
bucket is never touched, so this is safe to run again.
"""

from django.core.management.base import BaseCommand, CommandError

from datahealth.gps import tracks
from survey import track_objects


class Command(BaseCommand):
    help = "Write a blank file for every track record whose file is not in the bucket."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="List the files that would be made; write nothing.")

    def handle(self, *args, dry_run=False, **options):
        if not track_objects.can_write():
            raise CommandError("Writing to the bucket needs SPACES_LOCAL_DIR, or SPACES_ENDPOINT, "
                               "SPACES_KEY and SPACES_SECRET.")
        made = tracks.blank_files(report=self.stdout.write, dry_run=dry_run)
        for name in made:
            self.stdout.write(f"  {name}")
        self.stdout.write(f"{len(made):,} blank files {'would be ' if dry_run else ''}made")
