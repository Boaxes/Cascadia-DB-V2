"""
A track's StartTime and EndTime.

DB167 keeps them in Pacific local time. dbo and app keep UTC, like the track
files, so the build converts DB167's values (ETL/dbt/macros/track_times.sql)
and leaves the website's, which are UTC already. These tests check the
conversion across both daylight saving changes, the repeated hour, and, for
tracks made in DB167 and on the website, that the stored time is the file's own
first and last point time in UTC unless someone typed another one in DB167.
"""

import datetime
import os
from zoneinfo import ZoneInfo

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase

from datahealth.gps import tracks
from survey.models import Track
from TESTS.test_write_paths import WritePathTest, an_effort_with_no_track

PACIFIC = ZoneInfo("America/Los_Angeles")
UTC = datetime.timezone.utc


def fetch(sql, params=()):
    with connection.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def as_utc(local):
    return local.replace(tzinfo=PACIFIC).astimezone(UTC).replace(tzinfo=None)


def convert(local, file_time=None):
    return fetch("SELECT app.track_time_utc(%s, %s)", [local, file_time])[0][0]


class ConversionTests(TestCase):

    def setUp(self):
        if not fetch("SELECT to_regprocedure('app.track_time_utc(timestamp, timestamp)') IS NOT NULL")[0][0]:
            self.skipTest("The database has no app.track_time_utc(): run dbt run-operation create_persistent_tables.")

    def test_it_follows_the_zone_database_every_quarter_hour_around_both_changes(self):
        # Days around the spring change (2026-03-08) and the autumn one (2026-11-01), and the same in 2012.
        for first in (datetime.datetime(2026, 3, 7), datetime.datetime(2026, 10, 31), datetime.datetime(2012, 3, 10),
                      datetime.datetime(2012, 11, 3)):
            local = first
            while local < first + datetime.timedelta(days=3):
                repeated = local.month == 11 and local.day in (1, 4) and local.hour == 1
                missing = local.month == 3 and local.day in (8, 11) and local.hour == 2
                if not (repeated or missing):
                    self.assertEqual(convert(local), as_utc(local), local)
                local += datetime.timedelta(minutes=15)

    def test_a_summer_time_is_seven_hours_behind_and_a_winter_time_eight(self):
        self.assertEqual(convert(datetime.datetime(2026, 7, 1, 12)), datetime.datetime(2026, 7, 1, 19))
        self.assertEqual(convert(datetime.datetime(2026, 12, 1, 12)), datetime.datetime(2026, 12, 1, 20))

    def test_the_spring_change(self):
        self.assertEqual(convert(datetime.datetime(2026, 3, 8, 1, 59, 59)), datetime.datetime(2026, 3, 8, 9, 59, 59))
        self.assertEqual(convert(datetime.datetime(2026, 3, 8, 3, 0, 0)), datetime.datetime(2026, 3, 8, 10, 0, 0))
        # 02:30 never happened: it is read as the hour after, as the zone database does.
        self.assertEqual(convert(datetime.datetime(2026, 3, 8, 2, 30)), datetime.datetime(2026, 3, 8, 10, 30))

    def test_the_autumn_change_without_a_file_time_uses_standard_time(self):
        self.assertEqual(convert(datetime.datetime(2026, 11, 1, 0, 59, 59)), datetime.datetime(2026, 11, 1, 7, 59, 59))
        self.assertEqual(convert(datetime.datetime(2026, 11, 1, 1, 30)), datetime.datetime(2026, 11, 1, 9, 30))
        self.assertEqual(convert(datetime.datetime(2026, 11, 1, 2, 0, 0)), datetime.datetime(2026, 11, 1, 10, 0, 0))

    def test_the_repeated_hour_is_settled_by_the_files_time_when_it_falls_in_one_of_the_two_hours(self):
        local = datetime.datetime(2026, 11, 1, 1, 30)
        first_hour = datetime.datetime(2026, 11, 1, 8, 31)       # 01:31 PDT
        second_hour = datetime.datetime(2026, 11, 1, 9, 29)      # 01:29 PST
        self.assertEqual(convert(local, first_hour), datetime.datetime(2026, 11, 1, 8, 30))
        self.assertEqual(convert(local, second_hour), datetime.datetime(2026, 11, 1, 9, 30))
        # A file time from some other hour settles nothing.
        self.assertEqual(convert(local, datetime.datetime(2026, 11, 1, 12, 0)), datetime.datetime(2026, 11, 1, 9, 30))
        self.assertEqual(convert(local, datetime.datetime(2026, 11, 1, 7, 0)), datetime.datetime(2026, 11, 1, 9, 30))

    def test_the_file_time_is_ignored_outside_the_repeated_hour(self):
        self.assertEqual(convert(datetime.datetime(2026, 7, 1, 12), datetime.datetime(2020, 1, 1)),
                         datetime.datetime(2026, 7, 1, 19))

    def test_nothing_stays_nothing(self):
        self.assertIsNone(convert(None))

    def test_a_time_converted_to_pacific_and_back_is_the_same_time(self):
        for utc in (datetime.datetime(2026, 8, 26, 16, 21, 51), datetime.datetime(2026, 1, 5, 19, 30, 15),
                    datetime.datetime(2026, 3, 8, 10, 0), datetime.datetime(2026, 11, 1, 8, 30)):
            local = fetch("SELECT app.track_time_pacific(%s)", [utc])[0][0]
            self.assertEqual(local, utc.replace(tzinfo=UTC).astimezone(PACIFIC).replace(tzinfo=None))


class FileTimeTests(WritePathTest):
    """The stored times, against the track files in the stand-in bucket."""

    def times(self, key):
        """(file's first and last point, UTC) for a file in the folder of the original
        files, or None. The folder is named by TRACK_FILES_REFERENCE (the test bucket holds
        stand-ins, not the real files)."""
        folder = os.environ.get("TRACK_FILES_REFERENCE")
        path = os.path.join(folder, key) if folder else ""
        if not path or not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            result = tracks.process(f.read().decode("utf-8-sig", errors="replace"))
        if not result.first:
            return None
        return datetime.datetime.fromisoformat(result.first), datetime.datetime.fromisoformat(result.last)

    def seconds(self, a, b):
        return abs((a - b).total_seconds())

    def test_twenty_tracks_made_in_db167_hold_their_files_utc_times_unless_a_person_typed_others(self):
        if not os.environ.get("TRACK_FILES_REFERENCE"):
            self.skipTest("TRACK_FILES_REFERENCE names no folder of the original track files")
        rows = fetch("""
            SELECT t.legacy_track_id, t.object_key, t.start_time_utc, t.end_time_utc, r."StartTime", r."EndTime"
            FROM app.track t JOIN raw."TrackT" r ON r."TrackID" = t.legacy_track_id
            WHERE r."StartTime" IS NOT NULL AND r."EndTime" IS NOT NULL AND t.point_count > 0
              AND t.object_key IS NOT NULL AND lower(btrim(r."TrackFileName")) = lower(t.object_key)
            ORDER BY t.legacy_track_id LIMIT 300""")
        matched = typed = 0
        for track, key, start, end, raw_start, raw_end in rows:
            found = self.times(key)
            if found is None:
                continue
            first, last = found
            # Whatever was typed is converted as it was typed.
            self.assertLess(self.seconds(start, as_utc(raw_start)), 1, track)
            self.assertLess(self.seconds(end, as_utc(raw_end)), 1, track)
            if self.seconds(raw_start, first.replace(tzinfo=UTC).astimezone(PACIFIC).replace(tzinfo=None)) <= 5 and \
                    self.seconds(raw_end, last.replace(tzinfo=UTC).astimezone(PACIFIC).replace(tzinfo=None)) <= 5:
                # DB167 holds the file's own time, so the stored UTC time is the file's.
                self.assertLess(self.seconds(start, first), 5, track)
                self.assertLess(self.seconds(end, last), 5, track)
                matched += 1
            else:
                typed += 1
        self.assertGreaterEqual(matched, 20, f"{len(rows)} tracks, {typed} typed, {matched} matched")
        self.assertLess(typed, matched)        # a few were typed by hand; most are the file's own

    def test_the_website_writes_its_files_utc_times_and_the_database_holds_them_as_they_are(self):
        effort = an_effort_with_no_track()
        text = ("datetime_utc,latitude,longitude\n"
                "2026-08-26 16:21:51,42.05,-124.27\n2026-08-26 16:31:51,42.06,-124.27\n2026-08-27 02:08:03,42.07,-124.27\n")
        track_id, _ = tracks.add_file(self.user, SimpleUploadedFile("20260826-ROB-times.csv", text.encode()), effort=effort)
        start, end = fetch("SELECT start_time_utc, end_time_utc FROM app.track WHERE legacy_track_id = %s", [track_id])[0]
        self.assertEqual((start, end), (datetime.datetime(2026, 8, 26, 16, 21, 51), datetime.datetime(2026, 8, 27, 2, 8, 3)))
        # The file's times are recorded beside its line, for the build's use in the repeated hour.
        self.assertEqual(fetch("SELECT first_time, last_time FROM app.track_geometry WHERE object_key = %s",
                               ["20260826-ROB-times.csv"])[0], (start, end))
        # Filling it from another file sets that file's UTC times, not Pacific ones.
        track = Track.objects.get(legacy_track_id=track_id)
        tracks.fill(self.user, track, SimpleUploadedFile("again.csv", text.replace("2026-08-26 16:21:51", "2026-08-26 17:00:00").encode()))
        self.assertEqual(fetch("SELECT start_time_utc FROM app.track WHERE legacy_track_id = %s", [track_id])[0][0],
                         datetime.datetime(2026, 8, 26, 17, 0, 0))
