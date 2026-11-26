"""
Whether DB167 holds each change in the audit log (app.audit_log.db167_state),
the Audit Log pages that show it, and the SQL Server migration script.

The state is worked out by app.db167_state_of() in the database, which the
pipeline installs (ETL/dbt/macros/db167_state.sql, from
`dbt run-operation create_persistent_tables`) and runs against `raw` after
every build. These tests write entries straight into the log, for records of
DB167 no other entry is about, and read back what the function says.

Each test runs in a transaction that is rolled back afterwards.
"""

import datetime
import json
import re

from django.db import connection
from django.test import TestCase

from datahealth import audit
from TESTS.test_permissions import sign_in


def fetch(sql, params=()):
    with connection.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def log(action, table, pk, changes=None, legacy_pk=None, snapshot=None, restored_by=None, actor="test-person"):
    """Write an entry into the log and return its id."""
    return fetch("""
        INSERT INTO app.audit_log (actor_name, action, target_table, target_pk, legacy_pk, changes, snapshot, restored_by)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s) RETURNING id
    """, [actor, action, table, str(pk), None if legacy_pk is None else str(legacy_pk),
          json.dumps(changes) if changes is not None else None,
          json.dumps(snapshot) if snapshot is not None else None, restored_by])[0][0]


def state(entry_id):
    return fetch("SELECT app.db167_state_of(%s)", [entry_id])[0][0]


def change(old, new):
    return {"old": old, "new": new}


class StateTestCase(TestCase):

    def setUp(self):
        if not fetch("SELECT to_regprocedure('app.db167_state_of(bigint)') IS NOT NULL")[0][0]:
            self.skipTest("The database has no app.db167_state_of(): run dbt run-operation create_persistent_tables.")

    def quiet(self, table, key, column):
        """A row of raw, and its value of `column`, that no entry is about."""
        found = fetch(f"""
            SELECT "{key}", "{column}" FROM raw."{table}" r
            WHERE "{column}" IS NOT NULL AND btrim("{column}") <> ''
              AND NOT EXISTS (SELECT 1 FROM app.audit_log a
                              WHERE a.target_table = %s AND coalesce(a.legacy_pk, a.target_pk) = r."{key}"::text)
            ORDER BY "{key}" LIMIT 1
        """, [table])
        self.assertTrue(found, f"no row of raw.{table} without entries to test with")
        return found[0]


class UpdateStateTests(StateTestCase):

    def setUp(self):
        super().setUp()
        self.effort, self.locality = self.quiet("DailyEffortT", "DailyEffortID", "Locality")

    def locality_entry(self, old, new, **kwargs):
        return log("update", "DailyEffortT", "1234567890", {"Locality": change(old, new)},
                   legacy_pk=self.effort, **kwargs)

    def test_pending_while_DB167_still_holds_the_old_value(self):
        self.assertEqual(state(self.locality_entry(self.locality, "A New Place")), "pending")

    def test_applied_once_DB167_holds_the_new_value(self):
        self.assertEqual(state(self.locality_entry("An Old Place", self.locality)), "applied")

    def test_conflict_when_DB167_holds_neither(self):
        self.assertEqual(state(self.locality_entry("An Old Place", "A New Place")), "conflict")

    def test_the_old_value_is_compared_as_the_build_keeps_text(self):
        # The log holds cleaned text; DB167's is as it was typed.
        self.assertEqual(state(self.locality_entry(f"  {self.locality.upper()} ", "A New Place")), "pending")

    def test_the_new_value_is_compared_exactly(self):
        shouted = self.locality.upper() if self.locality.upper() != self.locality else self.locality.lower()
        self.assertEqual(state(self.locality_entry("An Old Place", shouted)), "conflict")

    def test_a_field_changed_again_later_is_applied_when_DB167_holds_the_later_value(self):
        first = self.locality_entry("An Old Place", "A Middle Place")
        second = self.locality_entry("A Middle Place", self.locality)
        self.assertEqual([state(first), state(second)], ["applied", "applied"])

    def test_a_field_whose_earlier_change_is_not_made_yet_is_pending_not_conflict(self):
        first = self.locality_entry(self.locality, "A Middle Place")
        second = self.locality_entry("A Middle Place", "A Last Place")
        self.assertEqual([state(first), state(second)], ["pending", "pending"])

    def test_every_field_must_be_applied_and_any_conflict_wins(self):
        # One effort for each case, so no entry is an earlier one of another.
        efforts = fetch("""
            SELECT "DailyEffortID", "Locality", "Region" FROM raw."DailyEffortT" r
            WHERE btrim("Locality") <> '' AND btrim("Region") <> ''
              AND NOT EXISTS (SELECT 1 FROM app.audit_log a WHERE a.target_table = 'DailyEffortT'
                              AND coalesce(a.legacy_pk, a.target_pk) = r."DailyEffortID"::text)
            ORDER BY 1 LIMIT 3""")
        self.assertEqual(len(efforts), 3)

        def both(effort, locality, region):
            return state(log("update", "DailyEffortT", "1234567890", {"Locality": locality, "Region": region},
                             legacy_pk=effort[0]))

        a, b, c = efforts
        self.assertEqual(both(a, change("Old", a[1]), change("Old", a[2])), "applied")
        self.assertEqual(both(b, change("Old", b[1]), change(b[2], "Elsewhere")), "pending")
        self.assertEqual(both(c, change("Old", c[1]), change("Old", "Elsewhere")), "conflict")

    def test_a_number_and_a_date_are_compared_as_numbers_and_dates(self):
        lat, = fetch('SELECT "Start Dec Lat" FROM raw."DailyEffortT" WHERE "DailyEffortID" = %s', [self.effort])[0]
        if lat is not None:
            entry = log("update", "DailyEffortT", "1", {"Start Dec Lat": change(0.5, str(lat))}, legacy_pk=self.effort)
            self.assertEqual(state(entry), "applied")
        when, = fetch('SELECT "Date" FROM raw."DailyEffortT" WHERE "DailyEffortID" = %s', [self.effort])[0]
        if when is not None:
            entry = log("update", "DailyEffortT", "1", {"Date": change("2000-01-01", str(when))}, legacy_pk=self.effort)
            self.assertEqual(state(entry), "applied")

    def test_each_field_has_its_own_standing(self):
        effort, locality, region = fetch("""
            SELECT "DailyEffortID", "Locality", "Region" FROM raw."DailyEffortT" r
            WHERE btrim("Locality") <> '' AND btrim("Region") <> ''
              AND NOT EXISTS (SELECT 1 FROM app.audit_log a WHERE a.target_table = 'DailyEffortT'
                              AND coalesce(a.legacy_pk, a.target_pk) = r."DailyEffortID"::text)
            ORDER BY 1 OFFSET 5 LIMIT 1""")[0]
        entry = log("update", "DailyEffortT", "1", {"Locality": change("Old", locality), "Region": change(region, "Elsewhere"),
                                                    "total_distance_nm": change(None, 4.5)}, legacy_pk=effort)
        fetch("SELECT app.refresh_db167_state(%s)", [entry])
        state_, fields = fetch("SELECT db167_state, db167_fields FROM app.audit_log WHERE id = %s", [entry])[0]
        self.assertEqual(state_, "pending")
        # total_distance_nm has no column in DB167: it is in no map.
        self.assertEqual(json.loads(fields) if isinstance(fields, str) else fields,
                         {"Locality": "applied", "Region": "pending"})

    def test_a_field_that_was_applied_stays_applied_when_DB167_changes_it_again(self):
        effort, locality = self.effort, self.locality
        entry = log("update", "DailyEffortT", "1", {"Locality": change("Old", locality)}, legacy_pk=effort)
        fetch("SELECT app.refresh_db167_state(%s)", [entry])
        self.assertEqual(fetch("SELECT db167_state, db167_fields ->> 'Locality' FROM app.audit_log WHERE id = %s", [entry])[0],
                         ("applied", "applied"))
        with connection.cursor() as cur:
            cur.execute('ALTER TABLE raw."DailyEffortT" DISABLE TRIGGER "DailyEffortT_frozen"')
            cur.execute('UPDATE raw."DailyEffortT" SET "Locality" = %s WHERE "DailyEffortID" = %s', ["DB167 Changed It", effort])
        self.assertEqual(state(entry), "applied")                    # state_of reads the field it kept
        fetch("SELECT app.refresh_db167_state(%s)", [entry])
        self.assertEqual(fetch("SELECT db167_state, db167_fields ->> 'Locality' FROM app.audit_log WHERE id = %s", [entry])[0],
                         ("applied", "applied"))
        # Forgetting checks it afresh: DB167 now holds neither the old nor the new value.
        fetch("SELECT app.refresh_db167_state(%s, true)", [entry])
        self.assertEqual(fetch("SELECT db167_state FROM app.audit_log WHERE id = %s", [entry])[0][0], "conflict")

    def test_associate_and_dissociate_are_updates_of_EffortID(self):
        track, effort_id = fetch('SELECT "TrackID", "EffortID" FROM raw."TrackT" WHERE "EffortID" IS NOT NULL '
                                 'AND NOT EXISTS (SELECT 1 FROM app.audit_log a WHERE a.target_table = \'TrackT\' '
                                 'AND a.target_pk = "TrackID"::text) ORDER BY 1 LIMIT 1')[0]
        held = log("associate", "TrackT", track, {"EffortID": change(None, effort_id)})
        waiting = log("dissociate", "TrackT", track, {"EffortID": change(effort_id, None)})
        self.assertEqual(state(held), "applied")
        self.assertEqual(state(waiting), "pending")


class TrackTimeStateTests(StateTestCase):
    """A track's StartTime and EndTime: the log keeps UTC, DB167 holds Pacific local
    time, so an entry is compared with DB167 after converting it to Pacific."""

    def setUp(self):
        super().setUp()
        found = fetch("""
            SELECT "TrackID", "StartTime" FROM raw."TrackT" r
            WHERE "StartTime" IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM app.audit_log a WHERE a.target_table = 'TrackT'
                              AND a.target_pk = r."TrackID"::text)
            ORDER BY 1 OFFSET 40 LIMIT 1""")
        self.assertTrue(found, "no track in raw with a StartTime and no entries")
        self.track, self.pacific = found[0]
        # What the website would hold: the same moment in UTC.
        self.utc = fetch("SELECT (%s::timestamp AT TIME ZONE 'America/Los_Angeles') AT TIME ZONE 'UTC'",
                         [self.pacific])[0][0]

    def entry(self, old, new):
        return log("update", "TrackT", self.track, {"StartTime": change(old, new)})

    def stamp(self, value):
        return value.strftime("%Y-%m-%d %H:%M:%S")

    def test_the_utc_value_the_website_holds_is_applied_when_DB167_holds_it_in_pacific(self):
        self.assertEqual(state(self.entry("2000-01-01 00:00:00", self.stamp(self.utc))), "applied")

    def test_it_is_not_applied_by_a_value_that_is_only_right_as_utc(self):
        # DB167 holds Pacific, so the entry's UTC text is not what it holds.
        self.assertNotEqual(self.stamp(self.utc), str(self.pacific))
        self.assertEqual(state(self.entry("2000-01-01 00:00:00", str(self.pacific))), "conflict")

    def test_it_is_pending_while_DB167_still_holds_the_old_value_in_pacific(self):
        later = self.utc + datetime.timedelta(hours=2)
        self.assertEqual(state(self.entry(self.stamp(self.utc), self.stamp(later))), "pending")

    def test_a_later_entry_that_changed_it_again_is_compared_the_same_way(self):
        first = self.entry("2000-01-01 00:00:00", "2001-01-01 00:00:00")
        second = self.entry("2001-01-01 00:00:00", self.stamp(self.utc))
        self.assertEqual([state(first), state(second)], ["applied", "applied"])

    def test_the_two_hours_of_a_clock_change_day_convert_with_daylight_saving(self):
        # Pacific 2026-03-08 03:00:00 is the first moment after the spring change: 10:00 UTC.
        raws = [r[0] for r in fetch("""SELECT "TrackID" FROM raw."TrackT" WHERE "StartTime" IS NOT NULL ORDER BY 1 LIMIT 2""")]
        with connection.cursor() as cur:
            cur.execute('ALTER TABLE raw."TrackT" DISABLE TRIGGER "TrackT_frozen"')
            cur.execute('UPDATE raw."TrackT" SET "StartTime" = %s WHERE "TrackID" = ANY(%s)', ["2026-03-08 03:00:00", raws])
        right = log("update", "TrackT", raws[0], {"StartTime": change("2000-01-01 00:00:00", "2026-03-08 10:00:00")})
        self.assertEqual(state(right), "applied")
        wrong = log("update", "TrackT", raws[1], {"StartTime": change("2000-01-01 00:00:00", "2026-03-08 11:00:00")})
        self.assertEqual(state(wrong), "conflict")


class RecordStateTests(StateTestCase):

    def test_a_record_the_website_changed_that_DB167_does_not_have_is_a_conflict(self):
        entry = log("update", "EffortCrewT", "99999999", {"CrewName": change("a", "b")})
        self.assertEqual(state(entry), "conflict")

    def test_but_pending_when_an_earlier_entry_creates_it(self):
        log("create", "TrackT", "99999999", {"TrackID": change(None, 99999999), "TrackFileName": change(None, "x.csv")})
        entry = log("associate", "TrackT", "99999999", {"EffortID": change(None, 5)})
        self.assertEqual(state(entry), "pending")

    def test_and_applied_when_a_later_entry_deleted_it(self):
        entry = log("update", "EffortCrewT", "99999999", {"CrewName": change("a", "b")})
        log("delete", "EffortCrewT", "99999999", snapshot={"EffortCrewT": [{"EffortCrewID": 99999999}]})
        self.assertEqual(state(entry), "applied")

    def test_an_entry_for_a_hashed_table_without_a_legacy_id_cannot_find_its_record(self):
        entry = log("update", "SightingT", "6359275879002753306", {"Comments": change("a", "b")})
        self.assertEqual(state(entry), "conflict")

    def test_a_hashed_record_is_found_by_its_legacy_id(self):
        sighting, comment = self.quiet("SightingT", "SightingID", "Comments")
        entry = log("update", "SightingT", "6359275879002753306", {"Comments": change(comment, "New")}, legacy_pk=sighting)
        self.assertEqual(state(entry), "pending")
        entry = log("update", "SightingT", "6359275879002753306", {"Comments": change("Old", comment)}, legacy_pk=sighting)
        self.assertEqual(state(entry), "applied")


class CreateAndDeleteStateTests(StateTestCase):

    def setUp(self):
        super().setUp()
        self.track, self.file = fetch('SELECT "TrackID", "TrackFileName" FROM raw."TrackT" r WHERE "TrackFileName" IS NOT NULL '
                                      'AND NOT EXISTS (SELECT 1 FROM app.audit_log a WHERE a.target_table = \'TrackT\' '
                                      'AND a.target_pk = r."TrackID"::text) ORDER BY 1 LIMIT 1')[0]

    def create(self, pk, file):
        return log("create", "TrackT", pk, {"TrackID": change(None, pk), "TrackFileName": change(None, file)})

    def test_a_created_row_DB167_does_not_have_is_pending(self):
        self.assertEqual(state(self.create(99999999, "new.csv")), "pending")

    def test_a_created_row_DB167_has_is_applied_whatever_the_capitals_of_its_file_name(self):
        self.assertEqual(state(self.create(self.track, self.file)), "applied")
        self.assertEqual(state(self.create(self.track, f" {self.file.upper()} ")), "applied")

    def test_the_trackid_used_for_another_file_is_a_conflict(self):
        self.assertEqual(state(self.create(self.track, "someone-elses.csv")), "conflict")

    def test_a_created_row_in_a_table_DB167_numbers_itself_has_nothing_to_write(self):
        self.assertEqual(state(log("create", "SightingT", "5", {"Comments": change(None, "x")})), "not_applicable")

    def test_a_record_made_and_deleted_on_the_website_never_reached_DB167(self):
        made = log("create", "TrackT", "99999999", {"TrackID": change(None, 99999999), "TrackFileName": change(None, "x.csv")})
        changed = log("update", "TrackT", "99999999", {"Comments": change(None, "a note")})
        matched = log("associate", "TrackT", "99999999", {"EffortID": change(None, 5)})
        # Not yet deleted: they wait for DB167.
        self.assertEqual([state(made), state(changed), state(matched)], ["pending"] * 3)
        removed = log("delete", "TrackT", "99999999", snapshot={"TrackT": [{"TrackID": 99999999}], "__order__": []})
        # Deleted: none of it is applied, so the build replays the lot, and the record stays gone.
        self.assertEqual([state(i) for i in (made, changed, matched, removed)], ["not_applicable"] * 4)

    def test_a_delete_is_pending_while_DB167_holds_the_record_the_website_made(self):
        track, file = fetch('SELECT "TrackID", "TrackFileName" FROM raw."TrackT" r WHERE "TrackFileName" IS NOT NULL '
                            'AND NOT EXISTS (SELECT 1 FROM app.audit_log a WHERE a.target_table = \'TrackT\' '
                            'AND a.target_pk = r."TrackID"::text) ORDER BY 1 LIMIT 1')[0]
        made = log("create", "TrackT", track, {"TrackID": change(None, track), "TrackFileName": change(None, file)})
        removed = log("delete", "TrackT", track, snapshot={"TrackT": [{"TrackID": track}], "__order__": []})
        self.assertEqual([state(made), state(removed)], ["applied", "pending"])

    def test_a_deleted_row_is_pending_while_DB167_has_it_and_applied_when_it_is_gone(self):
        crew, = fetch('SELECT "EffortCrewID" FROM raw."EffortCrewT" WHERE NOT EXISTS (SELECT 1 FROM app.audit_log a '
                      'WHERE a.target_table = \'EffortCrewT\' AND a.target_pk = "EffortCrewID"::text) ORDER BY 1 LIMIT 1')[0]
        present = log("delete", "EffortCrewT", crew, snapshot={"EffortCrewT": [{"EffortCrewID": crew}]})
        gone = log("delete", "EffortCrewT", 99999999, snapshot={"EffortCrewT": [{"EffortCrewID": 99999999}]})
        self.assertEqual([state(present), state(gone)], ["pending", "applied"])

    def test_a_deleted_record_with_a_hashed_key_is_found_by_the_legacy_id_in_its_copy(self):
        sighting, _ = self.quiet("SightingT", "SightingID", "Comments")
        present = log("delete", "SightingT", "1", snapshot={"SightingT": [{"id": 1, "SightingID": sighting}]})
        gone = log("delete", "SightingT", "2", snapshot={"SightingT": [{"id": 2, "SightingID": 99999999}]})
        self.assertEqual([state(present), state(gone)], ["pending", "applied"])


class NotApplicableStateTests(StateTestCase):

    def test_an_upload_changes_nothing_DB167_holds(self):
        entry = log("upload", "TrackT", "94", {"geom": change(None, "x"), "length_nm": change(None, 3.2)})
        self.assertEqual(state(entry), "not_applicable")

    def test_fields_the_build_works_out_have_no_column_in_DB167(self):
        entry = log("associate", "TrackT", "94", {"daily_effort_id": change(None, 5),
                                                  "track_status": change("unassociated", "available")})
        self.assertEqual(state(entry), "not_applicable")
        entry = log("update", "SightingT", "1", {"depth_m": change(None, 1.5)}, legacy_pk=11)
        self.assertEqual(state(entry), "not_applicable")

    def test_only_the_fields_DB167_has_are_compared(self):
        effort, locality = self.quiet("DailyEffortT", "DailyEffortID", "Locality")
        entry = log("update", "DailyEffortT", "1", {"Locality": change("Old", locality),
                                                    "total_distance_nm": change(None, 4.5)}, legacy_pk=effort)
        self.assertEqual(state(entry), "applied")

    def test_an_action_not_known_is_not_applicable(self):
        with connection.cursor() as cur:
            cur.execute("ALTER TABLE app.audit_log DROP CONSTRAINT IF EXISTS audit_log_action_check")
        for action in ("edit_file", "teleport"):
            entry = log(action, "TrackT", "94", {"EffortID": change(1, 2)})
            self.assertEqual(state(entry), "not_applicable", action)

    def test_a_table_DB167_does_not_have_is_not_applicable(self):
        self.assertEqual(state(log("update", "NoSuchT", "1", {"x": change(1, 2)})), "not_applicable")

    def test_an_entry_the_old_restore_put_back_cancels_out_with_its_restore(self):
        original = log("update", "EffortCrewT", "99999999", {"CrewName": change("a", "b")})
        restore = log("restore", "EffortCrewT", "99999999", {"CrewName": change("b", "a")})
        fetch("UPDATE app.audit_log SET restored_by = %s WHERE id = %s RETURNING id", [restore, original])
        self.assertEqual([state(original), state(restore)], ["not_applicable", "not_applicable"])

    def test_there_is_no_state_for_an_entry_that_is_not_there(self):
        self.assertIsNone(state(-1))


class RefreshTests(StateTestCase):

    def test_refresh_checks_every_entry_and_stamps_when(self):
        effort, locality = self.quiet("DailyEffortT", "DailyEffortID", "Locality")
        applied = log("update", "DailyEffortT", "1", {"Locality": change("Old", locality)}, legacy_pk=effort)
        upload = log("upload", "TrackT", "94", {"geom": change(None, "x")})
        total = fetch("SELECT count(*) FROM app.audit_log")[0][0]
        self.assertEqual(fetch("SELECT app.refresh_db167_state()")[0][0], total)
        rows = dict((i, (s, c is not None)) for i, s, c in fetch(
            "SELECT id, db167_state, db167_checked_at FROM app.audit_log WHERE id = ANY(%s)", [[applied, upload]]))
        self.assertEqual(rows, {applied: ("applied", True), upload: ("not_applicable", True)})

    def test_an_entry_is_stamped_only_when_its_state_changes(self):
        effort, locality = self.quiet("DailyEffortT", "DailyEffortID", "Locality")
        entry = log("update", "DailyEffortT", "1", {"Locality": change("Old", locality)}, legacy_pk=effort)
        fetch("SELECT app.refresh_db167_state()")
        # Pretend that check was long ago, then check again: nothing changed,
        # so the stamp must stay as it was.
        with connection.cursor() as cur:
            cur.execute("UPDATE app.audit_log SET db167_checked_at = '2000-01-01 00:00:00+00' WHERE id = %s", [entry])
        before = fetch("SELECT md5(string_agg(md5(to_jsonb(a)::text), '' ORDER BY id)) FROM app.audit_log a")[0][0]
        fetch("SELECT app.refresh_db167_state()")
        after = fetch("SELECT md5(string_agg(md5(to_jsonb(a)::text), '' ORDER BY id)) FROM app.audit_log a")[0][0]
        self.assertEqual(before, after)
        self.assertEqual(fetch("SELECT db167_checked_at < '2001-01-01+00' FROM app.audit_log WHERE id = %s", [entry])[0][0], True)
        # A change of state is stamped.
        with connection.cursor() as cur:
            cur.execute('ALTER TABLE raw."DailyEffortT" DISABLE TRIGGER "DailyEffortT_frozen"')
            cur.execute('UPDATE raw."DailyEffortT" SET "Locality" = %s WHERE "DailyEffortID" = %s', ["Another Place", effort])
        with connection.cursor() as cur:
            cur.execute("UPDATE app.audit_log SET db167_state = 'pending', db167_fields = NULL WHERE id = %s", [entry])
        fetch("SELECT app.refresh_db167_state(%s)", [entry])
        self.assertEqual(fetch("SELECT db167_checked_at > '2001-01-01+00' FROM app.audit_log WHERE id = %s", [entry])[0][0], True)

    def test_refresh_can_check_one_entry(self):
        upload = log("upload", "TrackT", "94", {"geom": change(None, "x")})
        self.assertEqual(fetch("SELECT app.refresh_db167_state(%s)", [upload])[0][0], 1)
        self.assertEqual(fetch("SELECT db167_state FROM app.audit_log WHERE id = %s", [upload])[0][0], "not_applicable")

    def test_a_new_entry_starts_pending_until_checked(self):
        entry = log("upload", "TrackT", "94", {"geom": change(None, "x")})
        self.assertEqual(fetch("SELECT db167_state, db167_checked_at FROM app.audit_log WHERE id = %s", [entry])[0],
                         ("pending", None))

    def test_an_entry_the_website_writes_is_checked_straight_away(self):
        entry = audit.record(None, "upload", "TrackT", 94, changes={"geom": change(None, "x")})
        self.assertEqual(fetch("SELECT db167_state, db167_checked_at IS NOT NULL FROM app.audit_log WHERE id = %s",
                               [entry])[0], ("not_applicable", True))

    def test_the_state_cannot_be_anything_else(self):
        entry = log("upload", "TrackT", "94")
        with self.assertRaises(Exception):
            with connection.cursor() as cur:
                cur.execute("UPDATE app.audit_log SET db167_state = 'maybe' WHERE id = %s", [entry])


class AuditPageTests(StateTestCase):

    def setUp(self):
        super().setUp()
        sign_in(self.client, "manager", "Data Manager")
        effort, locality = self.quiet("DailyEffortT", "DailyEffortID", "Locality")
        self.effort = effort
        self.ids = {
            "applied": log("update", "DailyEffortT", "1", {"Locality": change("Old", locality)}, legacy_pk=effort),
            "pending": log("update", "DailyEffortT", "2", {"Locality": change(locality, "New")}, legacy_pk=effort),
            "conflict": log("update", "EffortCrewT", "99999999", {"CrewName": change("a", "b")}),
            "not_applicable": log("upload", "TrackT", "94", {"geom": change(None, "x")}),
        }
        fetch("SELECT app.refresh_db167_state()")

    def page(self, query=""):
        response = self.client.get("/cascadia-admin/audit/" + query)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_every_entry_shows_whether_DB167_holds_it(self):
        html = self.page()
        self.assertIn("<th>DB167</th>", html)
        for state_name, label in (("pending", "Pending"), ("applied", "Applied"), ("conflict", "Conflict"),
                                  ("not_applicable", "Not Applicable")):
            self.assertIn(f'<span class="pill state-{state_name}">{label}</span>', html, state_name)

    def test_the_log_can_be_filtered_by_it(self):
        for state_name, entry_id in self.ids.items():
            html = self.page(f"?state={state_name}")
            self.assertIn(f"/cascadia-admin/audit/{entry_id}/", html, state_name)
            for other, other_id in self.ids.items():
                if other != state_name:
                    self.assertNotIn(f"/cascadia-admin/audit/{other_id}/", html, f"{state_name} showing {other}")
            self.assertRegex(html, rf'<option value="{state_name}"\s+selected>')

    def test_the_pager_is_shown_only_when_there_is_something_to_page(self):
        self.assertIn('class="pagination"', self.page())
        empty = self.page("?q=99999999999")
        self.assertIn("No changes match these filters.", empty)
        self.assertNotIn('class="pagination"', empty)

    def test_the_labels_are_in_title_case(self):
        html = self.page()
        for label in ("DB167 Status", "All Statuses", "Export SQL Server Migration Script"):
            self.assertIn(label, html, label)

    def test_an_entry_with_values_only_the_website_holds_says_which_is_which(self):
        effort, locality = self.quiet("DailyEffortT", "DailyEffortID", "Locality")
        mixed = log("update", "DailyEffortT", "3", {"Locality": change("Old", locality),
                                                    "total_distance_nm": change(None, 4.5)}, legacy_pk=effort)
        fetch("SELECT app.refresh_db167_state(%s)", [mixed])
        html = self.client.get(f"/cascadia-admin/audit/{mixed}/").content.decode()
        self.assertIn('<span class="pill state-applied">Applied</span>', html)
        self.assertIn("DB167 holds: Locality.", html)
        self.assertIn("DB167 has no column for Total Distance Nm, so only the website holds it.", html)
        self.assertIn('<span class="pill state-website">Website Only</span>', html)
        self.assertNotIn("DB167 holds this change.", html)

    def test_an_entry_says_so_and_when_it_was_checked(self):
        html = self.client.get(f"/cascadia-admin/audit/{self.ids['conflict']}/").content.decode()
        self.assertIn('<span class="pill state-conflict">Conflict</span>', html)
        self.assertIn("DB167 holds something else", html)
        self.assertIn("State Last Changed ", html)
        html = self.client.get(f"/cascadia-admin/audit/{self.ids['not_applicable']}/").content.decode()
        self.assertIn("Not Applicable", html)


class MigrationScriptTests(StateTestCase):

    URL = "/cascadia-admin/audit/migration-script/"

    def test_a_stranger_is_sent_to_sign_in(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_it_needs_the_permission_to_open_cascadia_admin(self):
        for role in ("Viewer", "Editor"):
            self.client.logout()
            sign_in(self.client, role.lower(), role)
            self.assertEqual(self.client.get(self.URL).status_code, 403, role)

    def test_a_data_manager_downloads_the_script(self):
        sign_in(self.client, "manager", "Data Manager")
        effort, locality = self.quiet("DailyEffortT", "DailyEffortID", "Locality")
        entry = log("update", "DailyEffortT", "6158310538023937915", {"Locality": change(locality, "O'Brien's Pt")},
                    legacy_pk=effort, actor="Doug Sandilands")
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response["Content-Disposition"], r'^attachment; filename="Cascadia-DB167-Migration-[\d-]+\.sql"$')
        body = response.content.decode("utf-8")
        self.assertTrue(body.startswith("\ufeff-- Cascadia Website Changes For DB167"))
        self.assertIn("SET XACT_ABORT OFF;", body)
        self.assertIn("BEGIN TRAN;", body)
        self.assertIn("IF XACT_STATE() = 1 COMMIT;", body)
        self.assertIn(f"-- Entry {entry},", body)
        self.assertIn("BEGIN TRY", body)
        self.assertIn(f"WHERE [DailyEffortID] = {effort} AND ", body)
        self.assertIn("SET [Locality] = N'O''Brien''s Pt'", body)

    def entries_in(self, url):
        body = self.client.get(url).content.decode("utf-8")
        return [int(n) for n in re.findall(r"^-- Entry (\d+),", body, re.M)], body

    def test_it_holds_every_entry_in_the_log_in_order(self):
        sign_in(self.client, "manager", "Data Manager")
        log("update", "EffortCrewT", "99999997", {"CrewName": change("a", "b")}, actor="Doug Sandilands")
        in_script, _ = self.entries_in(self.URL)
        self.assertEqual(in_script, [row[0] for row in fetch("SELECT id FROM app.audit_log ORDER BY id")])

    def test_the_audit_page_has_the_button(self):
        sign_in(self.client, "manager", "Data Manager")
        html = self.client.get("/cascadia-admin/audit/").content.decode()
        self.assertIn(f'href="{self.URL}"', html)
        self.assertIn("Export SQL Server Migration Script", html)
        self.assertNotIn("Corrections", html)

    def test_reading_it_changes_nothing(self):
        sign_in(self.client, "manager", "Data Manager")
        before = fetch("SELECT count(*), max(id), count(*) FILTER (WHERE db167_checked_at IS NOT NULL) FROM app.audit_log")
        self.client.get(self.URL)
        self.assertEqual(fetch("SELECT count(*), max(id), count(*) FILTER (WHERE db167_checked_at IS NOT NULL) "
                               "FROM app.audit_log"), before)
