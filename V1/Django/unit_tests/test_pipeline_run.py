"""The daily pipeline's helper (ETL/pipeline_run.py): knowing whether a database is on the new pipeline,
and working out how a run ended. Neither needs a database; detect() is given a stand-in for one."""

import importlib.util
import unittest
from pathlib import Path

from django.test import SimpleTestCase

SOURCE = Path(__file__).resolve().parents[2] / "ETL" / "pipeline_run.py"


def load():
    if not SOURCE.exists():
        raise unittest.SkipTest("ETL/ is not in this checkout (the web container mounts Django/ only)")
    spec = importlib.util.spec_from_file_location("pipeline_run", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Answer:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class Database:
    """Answers the four questions detect() asks, from a list of the columns the database has."""

    def __init__(self, columns, schemas=(), tables=()):
        self.columns, self.schemas, self.tables = set(columns), set(schemas), set(tables)

    def execute(self, sql, params=None):
        if "to_regnamespace" in sql:
            return Answer([(("build" in self.schemas),)])
        if "information_schema.columns" in sql:
            return Answer([(1,)] if tuple(params) in self.columns else [])
        if "to_regclass" in sql:
            schema, table = params[0].split(".")
            return Answer([((schema, table.strip('"')) in self.tables or None,)])
        raise AssertionError(sql)


OLD_COLUMNS = {("dbo", "SightingT", "SightingID"), ("app", "audit_log", "id"),
               ("raw", "TrackT", "TrackID"), ("raw", "VesselT", "VesselID"),
               ("dbo", "VesselListT", "vessel_id"), ("dbo", "VesselListT", "vessel_text")}
OLD_COLUMNS |= {("dbo", "TrackT", c) for c in ("TrackID", "file_name", "geom", "point_count", "length_nm", "track_status")}
OLD_TABLES = {("dbo", "SightingT"), ("app", "audit_log")}

NEW_COLUMNS = {("dbo", "SightingT", "id"), ("app", "audit_log", "legacy_pk")}
NEW_TABLES = {("dbo", "SightingT"), ("app", "audit_log"), ("app", "track_geometry"), ("app", "vessel_number")}


class DetectTests(SimpleTestCase):
    def setUp(self):
        self.run_module = load()

    def test_the_new_structure_is_migrated(self):
        state, _ = self.run_module.detect(Database(NEW_COLUMNS, {"build"}, NEW_TABLES))
        self.assertEqual(state, "migrated")

    def test_the_old_structure_is_not_migrated(self):
        state, _ = self.run_module.detect(Database(OLD_COLUMNS, set(), OLD_TABLES))
        self.assertEqual(state, "not_migrated")

    def test_the_old_structure_with_the_audit_log_already_widened_is_still_not_migrated(self):
        # dbt's first hook adds legacy_pk to an old audit log before the move is looked at.
        columns = OLD_COLUMNS | {("app", "audit_log", "legacy_pk")}
        state, _ = self.run_module.detect(Database(columns, set(), OLD_TABLES | {("app", "track_geometry")}))
        self.assertEqual(state, "not_migrated")

    def test_no_sighting_table_stops(self):
        with self.assertRaisesRegex(SystemExit, "neither the old structure nor the new one"):
            self.run_module.detect(Database(set(), set(), set()))

    def test_a_half_moved_database_stops(self):
        with self.assertRaisesRegex(SystemExit, "half moved"):
            self.run_module.detect(Database(NEW_COLUMNS, set(), NEW_TABLES))

    def test_a_missing_vessel_number_table_stops(self):
        with self.assertRaisesRegex(SystemExit, "app.vessel_number"):
            self.run_module.detect(Database(NEW_COLUMNS, {"build"}, NEW_TABLES - {("app", "vessel_number")}))

    def test_an_old_structure_missing_what_the_move_reads_stops(self):
        columns = OLD_COLUMNS - {("dbo", "TrackT", "file_name")}
        with self.assertRaisesRegex(SystemExit, r"dbo\.TrackT\.file_name"):
            self.run_module.detect(Database(columns, set(), OLD_TABLES))

    def test_an_old_structure_with_a_build_schema_stops(self):
        with self.assertRaisesRegex(SystemExit, "schema called build"):
            self.run_module.detect(Database(OLD_COLUMNS, {"build"}, OLD_TABLES))


def step(name, status="ok"):
    return {"step": name, "status": status, "seconds": 1}


GOOD = {"models": 68, "models_failed": 0, "tests_passed": 12, "tests_warned": 1, "tests_failed": 0,
        "tests_not_run": 0, "found": True}
CORE = [step(n) for n in ("deps", "check", "elementary-models", "import", "detect")]


class WorkOutTests(SimpleTestCase):
    def setUp(self):
        self.run_module = load()

    def result(self, done, build=GOOD, job="success", publish=True, trigger="workflow_dispatch"):
        return self.run_module.work_out(done, build, job, publish, trigger)

    def test_published(self):
        done = CORE + [step("cutover", "skipped"), step("build"), step("publish")]
        self.assertEqual(self.result(done), ("published", ""))

    def test_publishing_off_by_hand(self):
        done = CORE + [step("cutover", "skipped"), step("build"), step("publish", "skipped")]
        result, reason = self.result(done, publish=False)
        self.assertEqual(result, "not published")
        self.assertIn("started with publishing turned off", reason)

    def test_publishing_off_on_the_schedule_says_why(self):
        done = CORE + [step("cutover", "skipped"), step("build"), step("publish", "skipped")]
        result, reason = self.result(done, publish=False, trigger="schedule")
        self.assertEqual(result, "not published")
        self.assertIn("PIPELINE_PUBLISH", reason)

    def test_a_dry_run_on_an_unmoved_database_says_so(self):
        done = CORE + [step("cutover"), step("build", "skipped"), step("publish", "skipped")]
        result, reason = self.result(done, publish=False)
        self.assertEqual(result, "not published")
        self.assertIn("not on the new pipeline yet", reason)

    def test_a_failed_test_is_tests_failed(self):
        done = CORE + [step("cutover", "skipped"), step("build", "failed")]
        self.assertEqual(self.result(done, dict(GOOD, tests_failed=1), job="failure")[0], "tests failed")

    def test_a_failed_model_is_build_failed_even_with_failed_tests(self):
        done = CORE + [step("cutover", "skipped"), step("build", "failed")]
        result, reason = self.result(done, dict(GOOD, models_failed=1, tests_failed=2), job="failure")
        self.assertEqual(result, "build failed")
        self.assertIn("tests failed", reason)

    def test_a_build_with_no_results_is_build_failed(self):
        done = CORE + [step("cutover", "skipped"), step("build", "failed")]
        self.assertEqual(self.result(done, dict(GOOD, found=False), job="failure")[0], "build failed")

    def test_each_early_failure_has_its_own_result(self):
        for failed, expected in (("import", "import failed"), ("detect", "first-time move failed"),
                                 ("cutover", "first-time move failed"), ("publish", "publish failed"),
                                 ("check", "setup failed")):
            with self.subTest(failed):
                self.assertEqual(self.result([step(failed, "failed")], job="failure")[0], expected)

    def test_the_reports_own_steps_failing_do_not_change_the_result(self):
        done = CORE + [step("cutover", "skipped"), step("build"), step("publish"),
                       step("docs", "failed"), step("elementary-report", "failed")]
        self.assertEqual(self.result(done)[0], "published")

    def test_a_failure_before_any_step_ran_is_setup_failed(self):
        self.assertEqual(self.result([], job="failure")[0], "setup failed")

    def test_cancelled(self):
        self.assertEqual(self.result(CORE, job="cancelled")[0], "cancelled")

    def test_every_result_has_a_sentence_without_dashes_or_arrows(self):
        for sentence in self.run_module.RESULTS.values():
            self.assertNotRegex(sentence, "[\\u2014\\u2192\\u2190]")


class DatabaseAddressTests(SimpleTestCase):
    def setUp(self):
        self.run_module = load()

    def test_the_tunnel_replaces_the_host_and_port_and_keeps_the_rest(self):
        url = "postgresql://site:p%40ss@localhost:5432/cascadia?sslmode=require"
        self.assertEqual(self.run_module.tunnelled(url, 15432),
                         "postgresql://site:p%40ss@127.0.0.1:15432/cascadia?sslmode=require")

    def test_the_address_becomes_the_variables_dbt_reads(self):
        env = self.run_module.env_lines("postgresql://site:p%40ss@127.0.0.1:15432/cascadia?sslmode=require")
        self.assertEqual((env["PGHOST"], env["PGPORT"], env["PGUSER"], env["PGPASSWORD"], env["PGDATABASE"],
                          env["PGSSLMODE"]), ("127.0.0.1", "15432", "site", "p@ss", "cascadia", "require"))
