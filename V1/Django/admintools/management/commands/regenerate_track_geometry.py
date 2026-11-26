"""
Rebuild the line of every GPS file in the bucket, or of the files named.

    python manage.py regenerate_track_geometry --dry-run     say what would change
    python manage.py regenerate_track_geometry               rewrite what changed
    python manage.py regenerate_track_geometry --key K ...   only these files

This is the only way an existing row of raw.track_geometry changes. Run it
after changing the cleaning or line rules in gps/tracks.py; the build itself
never recomputes a line. The bucket is only read.

    python manage.py regenerate_track_geometry --seed-from-dbo

is for the move to the new pipeline, once: it fills raw.track_geometry from the
lines the old import stored on dbo."TrackT", for every file in the bucket,
without recomputing any of them. A --dry-run afterwards should then report no
changes, which shows the bucket and the code reproduce what is live.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from admintools.gps import tracks
from survey import track_objects


class Command(BaseCommand):
    help = "Rebuild the line of every GPS file in the bucket from the file itself."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Read every file and report what would change; write nothing.")
        parser.add_argument("--key", action="append", dest="keys",
                            help="Only this file. Repeat for more than one.")
        parser.add_argument("--seed-from-dbo", action="store_true",
                            help="Once, at migration: copy each file's line from dbo.TrackT.")

    def handle(self, *args, dry_run=False, keys=None, seed_from_dbo=False, **options):
        if not track_objects.can_write():
            raise CommandError("Reading the bucket file by file needs SPACES_ENDPOINT, "
                               "SPACES_KEY and SPACES_SECRET.")
        with connection.cursor() as cur:
            cur.execute("SELECT to_regclass('raw.track_geometry') IS NOT NULL")
            if not cur.fetchone()[0]:
                raise CommandError("raw.track_geometry does not exist yet. Run "
                                   "`dbt run-operation create_persistent_tables` first.")
        if seed_from_dbo:
            return self.seed(dry_run)

        outcome = tracks.regenerate(keys=keys, dry_run=dry_run, report=self.stdout.write)
        verb = "would change" if dry_run else "changed"
        self.stdout.write(
            f"{len(outcome['unchanged']):,} unchanged, {len(outcome['changed']):,} {verb}, "
            f"{len(outcome['added']):,} {'would be ' if dry_run else ''}added, "
            f"{len(outcome['not_in_bucket']):,} not in the bucket")
        for label in ("changed", "added", "not_in_bucket"):
            for key in outcome[label]:
                self.stdout.write(f"  {label:<14} {key}")

    def seed(self, dry_run):
        listing = track_objects.listing()
        with connection.cursor() as cur:
            cur.execute("SELECT count(*) FROM raw.track_geometry")
            if cur.fetchone()[0]:
                raise CommandError("raw.track_geometry already has rows; seeding is for an empty table.")
            # Every track record's line, by file name. Several records can
            # name the same file; they were all given the same line.
            cur.execute("""
                SELECT lower(file_name), count(DISTINCT geom::text), max(geom::text),
                       max(point_count), max(length_nm)
                FROM   dbo."TrackT" WHERE file_name IS NOT NULL
                GROUP  BY 1
            """)
            lines = {r[0]: r[1:] for r in cur.fetchall()}

        conflicts = [k for k, (n, *_rest) in lines.items() if n > 1]
        if conflicts:
            raise CommandError(f"Track records naming the same file disagree about its line: "
                               f"{', '.join(sorted(conflicts)[:10])}")
        rows = []
        for key, (stored, etag, size) in sorted(listing.items()):
            _n, geom, points, length = lines.get(key.lower(), (0, None, None, None))
            rows.append((key, etag, geom, points, length))
        in_bucket = {k.lower() for k in listing}
        line_without_file = sorted(k for k, (n, geom, *_r) in lines.items()
                                   if geom and k not in in_bucket)

        self.stdout.write(f"{len(rows):,} files in the bucket, "
                          f"{sum(1 for r in rows if r[2]):,} with a line from dbo.TrackT, "
                          f"{sum(1 for r in rows if not r[2]):,} without one")
        if line_without_file:
            self.stdout.write(f"{len(line_without_file)} lines in dbo.TrackT have no file in the "
                              f"bucket and are not carried over: {', '.join(line_without_file[:10])}")
        if dry_run:
            return
        with transaction.atomic(), connection.cursor() as cur:
            cur.executemany("""
                INSERT INTO raw.track_geometry (object_key, etag, geom, point_count, length_nm)
                VALUES (%s, %s, %s::geometry, %s, %s)
            """, rows)
        self.stdout.write(f"seeded {len(rows):,} rows")
