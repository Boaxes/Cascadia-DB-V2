"""
Tests run against a copy of your local database: whatever ops/pull-db.sh last
put there, frozen as `reference` by ops/make-reference.sh, and copied afresh
for each run so a test can write freely and nothing carries over.

    ops/test.sh reference        (PowerShell: ops\\test.ps1 reference)

Every model the application reads sits on a view (`managed = False`), so a
test database built by Django's migrations would have nothing in it to read.

The bucket is a temporary folder (SPACES_LOCAL_DIR), holding a stand-in file
for every track file the data says is stored. Uploads in the tests land there,
never in the real bucket.
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
        # ...and the checks of the files written there (survey/track_checks.py).
        self.checks = tempfile.mkdtemp(prefix="test-checks-")
        settings.TRACK_CHECKS_DIR = self.checks

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

        from datahealth.trackfix import HAS_FILE

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

        # The reference copy predates the audit log's legacy_pk and db167_state
        # columns, which the pipeline adds (ETL/dbt/macros/schemas.sql,
        # persistent_tables).
        with connection.cursor() as cur:
            cur.execute("ALTER TABLE app.audit_log ADD COLUMN IF NOT EXISTS legacy_pk text")
            cur.execute("ALTER TABLE app.audit_log ADD COLUMN IF NOT EXISTS db167_state text NOT NULL DEFAULT 'pending'")
            cur.execute("ALTER TABLE app.audit_log ADD COLUMN IF NOT EXISTS db167_checked_at timestamptz")
            cur.execute("ALTER TABLE app.audit_log ADD COLUMN IF NOT EXISTS db167_fields jsonb")

            # ...and the edit_file action, which a copy built before it lacks.
            cur.execute("ALTER TABLE app.audit_log DROP CONSTRAINT IF EXISTS audit_log_action_check")
            cur.execute("""
                ALTER TABLE app.audit_log ADD CONSTRAINT audit_log_action_check
                CHECK (action IN ('create', 'update', 'delete', 'restore', 'upload',
                                  'associate', 'dissociate', 'edit_file'))""")

        # The reference copy predates the Django admin's log table, the feedback
        # pictures' table and the roles.
        call_command("migrate", "admin", verbosity=0)
        call_command("migrate", "feedback", verbosity=0)
        call_command("migrate", "datahealth", verbosity=0)
        call_command("setup_access", stdout=open(os.devnull, "w"))
        # The land outline lives in public, which the reference copy may not hold.
        call_command("load_land", stdout=open(os.devnull, "w"))

        print(f"Test database copied in {time.monotonic() - started:.0f}s, "
              f"with {len(stored):,} track files in the stand-in bucket.", file=sys.stderr)

    def teardown_databases(self, old_config, **kwargs):
        super().teardown_databases(old_config, **kwargs)
        with _admin_connection() as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {_ident(_test_name())} WITH (FORCE)")
        shutil.rmtree(self.bucket, ignore_errors=True)
        shutil.rmtree(self.checks, ignore_errors=True)
