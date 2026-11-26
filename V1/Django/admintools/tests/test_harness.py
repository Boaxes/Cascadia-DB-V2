"""
The harness itself: that tests reach a copy of the live data, and that the GPS
cleaner can be exercised without a database. Tests of the website's write
paths come later.
"""

from django.db import connection
from django.test import SimpleTestCase, TestCase

from admintools.gps import tracks as clean


class DatabaseCopyTests(TestCase):

    def test_reads_the_copy_of_live(self):
        with connection.cursor() as cur:
            cur.execute("SELECT count(*) FROM app.sighting")
            self.assertGreater(cur.fetchone()[0], 0)

    def test_is_not_the_working_database(self):
        self.assertTrue(connection.settings_dict["NAME"].startswith("test_"))


class TimestampTests(SimpleTestCase):

    def test_minute_only_times_gain_seconds(self):
        self.assertEqual(clean.normalise_timestamp("2013-01-04 19:57"),
                         "2013-01-04 19:57:00")

    def test_single_digit_hours_are_padded(self):
        self.assertEqual(clean.normalise_timestamp("2013-01-04 9:05:07"),
                         "2013-01-04 09:05:07")

    def test_impossible_times_are_rejected(self):
        for value in ["2013-01-04 16:46:60", "2013-13-01 00:00:00", "", "not a time"]:
            with self.subTest(value=value):
                self.assertIsNone(clean.normalise_timestamp(value))
