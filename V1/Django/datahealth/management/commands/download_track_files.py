"""
Copy the GPS files out of the bucket into a folder on this machine.

    python manage.py download_track_files tracks        into the folder tracks
    python manage.py download_track_files               into SPACES_LOCAL_DIR
    python manage.py download_track_files tracks --all  with _versions/ and _deleted/ too

A local copy of the site has no way to open, draw or save a track unless it can
reach the files. Pointing it at the real bucket would let a test save change
the only authoritative copy, so the files are copied down instead and the site
is pointed at the folder: set SPACES_LOCAL_DIR to it, and every read and write
goes to the folder and never to the bucket.

The bucket is only read. The command needs SPACES_ENDPOINT, SPACES_KEY and
SPACES_SECRET; pass them in the environment for this one run rather than
keeping the key in .env. A file already in the folder and unchanged is skipped,
so the command can be run again to fetch what is new.
"""

import os

from django.core.management.base import BaseCommand, CommandError

from survey import track_objects


class Command(BaseCommand):
    help = "Copy the GPS files from the bucket into a local folder."

    def add_arguments(self, parser):
        parser.add_argument("folder", nargs="?",
                            help="Where the files go. Defaults to SPACES_LOCAL_DIR.")
        parser.add_argument("--all", action="store_true", dest="everything",
                            help="Also copy the earlier versions and the deleted files.")

    def handle(self, *args, folder=None, everything=False, **options):
        folder = folder or os.environ.get("SPACES_LOCAL_DIR", "")
        if not folder:
            raise CommandError("Name a folder, or set SPACES_LOCAL_DIR.")
        fetched = []

        def report(key):
            fetched.append(key)
            if len(fetched) % 100 == 0:
                self.stdout.write(f"  {len(fetched):,} files so far")

        try:
            downloaded, unchanged = track_objects.download(folder, everything, report)
        except RuntimeError as error:
            raise CommandError(str(error))
        self.stdout.write(f"{downloaded:,} downloaded, {unchanged:,} already there, in {folder}")
