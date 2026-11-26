"""
Tests run against a database built the way the live one is: a copy of
`reference`, the untouched pull of the live database, with the pipeline set up
on it and run.

Every model the application reads sits on a view the pipeline creates
(`managed = False`), so a test database built by Django's migrations would
have nothing in it to read. A copy of `reference` has everything, and making it
fresh for each run means a test can write freely and nothing carries over.

    ops/make-reference.sh                                  # once, after ops/pull-db.sh
    docker compose exec web python manage.py test

Before any test runs, the copy is set up exactly as the switch to the new
pipeline sets up the live database:

  1. raw's lists (species, event code names, vessels) are seeded from dbo;
  2. raw.track_geometry is seeded from the lines on dbo.TrackT, for every file
     in the bucket;
  3. dbt builds dbo and app, every test passes, and the build is swapped in.

The bucket is a temporary folder (SPACES_LOCAL_DIR), holding a stand-in file
for every track file the live data says is stored. Uploads in the tests land
there, never in the real bucket. Setting it up takes about a minute.
"""

import os
import shutil
import sys
import tempfile
import time

import psycopg
from django.conf import settings
from django.test.runner import DiscoverRunner

REFERENCE = os.environ.get("REFERENCE_DB", "reference")

# A file the track tool's status calls stored. Only its name matters to the
# seed; a test that reads a file back uploads its own.
STAND_IN = b"datetime_utc,latitude,longitude\n"


def _admin_connection():
    db = settings.DATABASES["default"]
    return psycopg.connect(
        host=db["HOST"], port=db["PORT"] or 5432, user=db["USER"],
        password=db["PASSWORD"], dbname="postgres", autocommit=True)


def _ident(name):
    return '"' + name.replace('"', '""') + '"'


def _test_name():
    return settings.DATABASES["default"].get("TEST", {}).get("NAME") \
        or "test_" + settings.DATABASES["default"]["NAME"]


class ReferenceCopyRunner(DiscoverRunner):

    def setup_databases(self, **kwargs):
        # The bucket first: nothing may reach the real one, even by accident.
        self.bucket = tempfile.mkdtemp(prefix="test-bucket-")
        os.environ["SPACES_LOCAL_DIR"] = self.bucket

        with _admin_connection() as conn:
            found = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s",
                                 [REFERENCE]).fetchone()
            if not found:
                raise RuntimeError(
                    f"There is no {REFERENCE!r} database to copy. Run ops/pull-db.sh, "
                    "then ops/make-reference.sh, and try again.")
            conn.execute(f"DROP DATABASE IF EXISTS {_ident(_test_name())} WITH (FORCE)")
            conn.execute(f"CREATE DATABASE {_ident(_test_name())} TEMPLATE {_ident(REFERENCE)}")
        # The copy already holds Django's own tables, so it is used as it is
        # rather than created and migrated.
        self.keepdb = True
        old_config = super().setup_databases(**kwargs)
        self._set_up_pipeline()
        return old_config

    def _set_up_pipeline(self):
        from django.core.management import call_command
        from django.db import connection

        from admintools.trackfix import HAS_FILE
        from admintools.tests import rebuild

        started = time.monotonic()
        with connection.cursor() as cur:
            # A fresh import freezes raw.EventCodeT; live's has no trigger yet.
            cur.execute("""
                DO $$ BEGIN
                  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'EventCodeT_frozen') THEN
                    CREATE TRIGGER "EventCodeT_frozen" BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
                        ON raw."EventCodeT" FOR EACH STATEMENT EXECUTE FUNCTION raw.frozen();
                  END IF;
                END $$""")
            cur.execute('SELECT DISTINCT ON (lower(file_name)) file_name FROM dbo."TrackT" '
                        'WHERE file_name IS NOT NULL AND track_status = ANY(%s) '
                        'ORDER BY lower(file_name), file_name', [list(HAS_FILE)])
            stored = [row[0] for row in cur.fetchall()]
        for name in stored:
            with open(os.path.join(self.bucket, name), "wb") as f:
                f.write(STAND_IN)

        rebuild.dbt("run-operation", "seed_lists_from_dbo")
        call_command("regenerate_track_geometry", seed_from_dbo=True, stdout=open(os.devnull, "w"))
        rebuild.build_and_swap()
        print(f"Test database built by the pipeline in {time.monotonic() - started:.0f}s, "
              f"with {len(stored):,} track files in the stand-in bucket.", file=sys.stderr)

    def teardown_databases(self, old_config, **kwargs):
        super().teardown_databases(old_config, **kwargs)
        with _admin_connection() as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {_ident(_test_name())} WITH (FORCE)")
        shutil.rmtree(self.bucket, ignore_errors=True)
