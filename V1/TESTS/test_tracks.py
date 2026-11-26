"""
gps/tracks.py without a database or a bucket: cleaning and building a line.

The website's upload and link paths, which need both, are tested separately.
"""

from django.test import SimpleTestCase

from datahealth.gps import tracks

RAW = (
    "DateTimeUTC,Latitude,Longitude\r\n"
    "2013-01-04 9:57,33.460763487964869,-117.69176004454494\r\n"
    "2013-01-04 10:05:07,33.47,-117.70\r\n"
    "2013-01-04 10:06:00,33.48,17.70\r\n"          # east of Greenwich: dropped
    "2013-01-04 10:07:00,not-a-number,-117.71\r\n"  # not a number: dropped
    "2013-01-04 16:46:60,33.49,-117.72\r\n"         # second 60: dropped
)


class CleaningTests(SimpleTestCase):

    def test_cleans_to_the_one_shape(self):
        cleaned, dropped = tracks.clean_text(RAW)
        self.assertEqual(cleaned,
                         "datetime_utc,latitude,longitude\n"
                         "2013-01-04 09:57:00,33.460763487964869,-117.69176004454494\n"
                         "2013-01-04 10:05:07,33.47,-117.70\n")
        self.assertEqual(dropped, 3)

    def test_cleaning_a_cleaned_file_changes_nothing(self):
        # The bucket holds cleaned files, and regenerating reads them back
        # through the same cleaner. Before `datetime_utc` was accepted as a
        # time column this dropped every row.
        once, _ = tracks.clean_text(RAW)
        twice, dropped = tracks.clean_text(once)
        self.assertEqual(twice, once)
        self.assertEqual(dropped, 0)

    def test_columns_are_found_by_name_not_position(self):
        cleaned, _ = tracks.clean_text("lon,extra,lat,datetime\n-120.5,,35.25,2020-01-01 00:00:00\n")
        self.assertEqual(cleaned, "datetime_utc,latitude,longitude\n2020-01-01 00:00:00,35.25,-120.5\n")


class LineTests(SimpleTestCase):

    def test_a_long_silence_starts_a_new_line(self):
        cleaned = ("datetime_utc,latitude,longitude\n"
                   "2020-01-01 00:00:00,35.0,-120.0\n"
                   "2020-01-01 00:10:00,35.1,-120.1\n"
                   "2020-01-01 02:00:00,36.0,-121.0\n"     # 110 minutes later
                   "2020-01-01 02:10:00,36.1,-121.1\n")
        wkt, points = tracks.to_wkt(cleaned)
        self.assertEqual(points, 4)
        self.assertEqual(wkt, "SRID=4326;MULTILINESTRING((-120.000000 35.000000,-120.100000 35.100000),"
                              "(-121.000000 36.000000,-121.100000 36.100000))")

    def test_a_file_with_no_usable_run_has_no_line(self):
        wkt, points = tracks.to_wkt("datetime_utc,latitude,longitude\n2020-01-01 00:00:00,35.0,-120.0\n")
        self.assertIsNone(wkt)
        self.assertEqual(points, 1)


class ProcessTests(SimpleTestCase):

    def test_process_is_clean_then_line(self):
        result = tracks.process(RAW)
        cleaned, dropped = tracks.clean_text(RAW)
        self.assertEqual(result.cleaned, cleaned)
        self.assertEqual(result.dropped, dropped)
        self.assertEqual((result.wkt, result.points), tracks.to_wkt(cleaned))
        self.assertEqual((result.first, result.last), ("2013-01-04 09:57:00", "2013-01-04 10:05:07"))

    def test_processing_a_cleaned_file_gives_the_same_line(self):
        # What regenerating from the bucket relies on.
        first = tracks.process(RAW)
        again = tracks.process(first.cleaned)
        self.assertEqual((again.cleaned, again.wkt, again.points),
                         (first.cleaned, first.wkt, first.points))
