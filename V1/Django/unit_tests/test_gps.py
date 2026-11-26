"""GPS cleaning and line building: the cases a real file has tripped on."""

import datetime

from django.test import SimpleTestCase

from datahealth.gps import tracks

# The file from issue #7: a UTC and a local time column, a stationary boat.
ISSUE_7 = (
    "DatetimeUTC,DatetimeLocal,Latitude,Longitude\n"
    "2025-12-15 15:38:30,2025-12-15 07:38:30,36.609056,-121.8935645\n"
    "2025-12-15 15:38:31,2025-12-15 07:38:31,36.6090531666667,-121.8935625\n"
    "2025-12-15 15:38:32,2025-12-15 07:38:32,36.60905,-121.893562166667\n"
    "2025-12-15 15:38:33,2025-12-15 07:38:33,36.6090496666667,-121.893563666667\n"
    "2025-12-15 15:38:34,2025-12-15 07:38:34,36.6090491666667,-121.893565166667\n"
    "2025-12-15 15:38:35,2025-12-15 07:38:35,36.6090506666667,-121.893567333333\n"
    "2025-12-15 15:38:36,2025-12-15 07:38:36,36.6090506666667,-121.893567333333\n"
    "2025-12-15 15:38:37,2025-12-15 07:38:37,36.6090506666667,-121.893567333333\n"
    "2025-12-15 15:38:38,2025-12-15 07:38:38,36.6090506666667,-121.893567333333\n"
)


class FileTests(SimpleTestCase):

    def test_a_file_with_utc_and_local_columns_is_read_by_the_utc_one(self):
        result = tracks.process(ISSUE_7)
        self.assertEqual(result.dropped, 0)
        self.assertEqual(result.points, 9)
        self.assertEqual((result.first, result.last),
                         ("2025-12-15 15:38:30", "2025-12-15 15:38:38"))
        self.assertTrue(result.wkt.startswith("SRID=4326;MULTILINESTRING(("))

    def test_a_file_without_the_expected_columns_is_all_dropped_not_a_crash(self):
        cleaned, dropped = tracks.clean_text("when,y,x\n2020-01-01 00:00:00,35.0,-120.0\n")
        self.assertEqual(cleaned, tracks.CLEAN_HEADER + "\n")
        self.assertEqual(dropped, 1)


class LineTests(SimpleTestCase):

    @staticmethod
    def _rows(*times):
        return [(-120.0, 35.0, t) for t in times]

    def test_exactly_the_gap_length_is_still_one_line(self):
        runs = tracks.split_on_gaps(self._rows("2020-01-01 00:00:00", "2020-01-01 00:30:00"))
        self.assertEqual(len(runs), 1)

    def test_one_second_past_the_gap_starts_a_new_line(self):
        runs = tracks.split_on_gaps(self._rows("2020-01-01 00:00:00", "2020-01-01 00:30:01"))
        self.assertEqual(len(runs), 2)

    def test_a_straight_run_keeps_only_its_ends_and_a_corner_survives(self):
        straight = [(-120.0, 35.0), (-120.001, 35.0), (-120.002, 35.0), (-120.003, 35.0)]
        self.assertEqual(tracks.simplify(straight), [straight[0], straight[-1]])
        bent = [(-120.0, 35.0), (-120.002, 35.01), (-120.004, 35.0)]
        self.assertEqual(tracks.simplify(bent), bent)

    def test_coordinates_are_written_longitude_first_at_six_places(self):
        wkt, _ = tracks.to_wkt("datetime_utc,latitude,longitude\n"
                               "2020-01-01 00:00:00,35.12345678,-120.98765432\n"
                               "2020-01-01 00:00:01,35.2,-121.0\n")
        self.assertEqual(wkt, "SRID=4326;MULTILINESTRING((-120.987654 35.123457,-121.000000 35.200000))")


class LineErrorTests(SimpleTestCase):
    """What the editor's Save checks: every line clean_text would drop, with why."""

    GOOD = ("datetime_utc,latitude,longitude\n"
            "2020-01-01 00:00:00,35.0,-120.0\n")

    def test_a_good_file_has_no_errors(self):
        self.assertEqual(tracks.line_errors(self.GOOD), [])
        self.assertEqual(tracks.line_errors(self.GOOD.replace("\n", "\r\n")), [])

    def test_each_bad_line_is_named_with_its_reason(self):
        text = (self.GOOD +
                "2020-01-01 00:01:00,4278.12,-120.0\n"      # line 3
                "2020-01-01 00:02:00,35.0,117.5\n"          # line 4: east of Greenwich
                "yesterday,35.0,-120.0\n"                   # line 5
                "2020-01-01 00:04:00,35.0\n"                # line 6
                "2020-01-01 00:05:00,north,-120.0\n")       # line 7
        found = dict(tracks.line_errors(text))
        self.assertEqual(sorted(found), [3, 4, 5, 6, 7])
        self.assertIn("Latitude 4278.12 is outside -90 to 90", found[3])
        self.assertIn("must be west of 0", found[4])
        self.assertIn("Date and time must look like", found[5])
        self.assertIn("Needs three values", found[6])
        self.assertIn("must be numbers", found[7])

    def test_blank_lines_are_not_errors_and_line_numbers_count_them(self):
        found = tracks.line_errors(self.GOOD + "\n\n2020-01-01 00:01:00,95.0,-120.0\n")
        self.assertEqual([n for n, _ in found], [5])

    def test_a_header_that_names_no_columns_is_the_one_error(self):
        self.assertEqual([n for n, _ in tracks.line_errors("when,y,x\n2020-01-01 00:00:00,35.0,-120.0\n")], [1])

    def test_anything_with_no_errors_is_kept_whole_by_cleaning(self):
        cleaned, dropped = tracks.clean_text(self.GOOD)
        self.assertEqual((cleaned, dropped), (self.GOOD, 0))

    def test_every_line_with_an_error_is_one_cleaning_drops(self):
        text = self.GOOD + "2020-01-01 00:01:00,95.0,-120.0\n2020-01-01 00:02:00,35.0,+10.0\n"
        self.assertEqual(len(tracks.line_errors(text)), tracks.clean_text(text)[1])


class SuggestionTests(SimpleTestCase):

    def test_the_effort_day_is_the_pacific_date_of_the_first_point(self):
        # 03:00 UTC on the 25th is still the evening of the 24th on the coast.
        self.assertEqual(str(tracks.pacific_date("2024-09-25 03:00:00")), "2024-09-24")
        self.assertEqual(str(tracks.pacific_date("2024-09-24 16:05:27")), "2024-09-24")
        # And in winter, eight hours behind rather than seven.
        self.assertEqual(str(tracks.pacific_date("2024-01-15 07:30:00")), "2024-01-14")

    def test_the_vessel_is_the_code_after_the_date_in_the_file_name(self):
        self.assertEqual(tracks.vessel_code_in("20240316-ROB-7to1500.csv"), "ROB")
        self.assertEqual(tracks.vessel_code_in("20250827-mus_GPX-pc.csv"), "MUS")
        self.assertIsNone(tracks.vessel_code_in("track.csv"))


class TrackTimeTests(SimpleTestCase):
    """A track's StartTime and EndTime are the file's own first and last time, in UTC."""

    def test_a_filled_or_imported_file_sets_the_files_utc_times(self):
        result = tracks.process(ISSUE_7)
        values = tracks._line_values(None, tracks.Processed("x", 0, None, 9, result.first, result.last), "available")
        self.assertEqual((values["StartTime"], values["EndTime"]), ("2025-12-15 15:38:30", "2025-12-15 15:38:38"))

    def test_a_file_with_no_points_sets_no_times(self):
        values = tracks._line_values(None, tracks.Processed("x", 0, None, 0, None, None), "blank")
        self.assertEqual((values["StartTime"], values["EndTime"]), (None, None))


class PositionsTextTests(SimpleTestCase):
    """The text an Effort's recorded positions become, before it is a file."""

    def test_one_row_per_position_in_the_order_given_in_the_clean_format(self):
        text = tracks.positions_text([
            (datetime.datetime(2024, 9, 24, 16, 5, 27), 47.1, -122.5),
            (datetime.datetime(2024, 9, 24, 16, 9, 0), 47.123456789, -122.6),
        ])
        self.assertEqual(text, "datetime_utc,latitude,longitude\n"
                               "2024-09-24 16:05:27,47.100000,-122.500000\n"
                               "2024-09-24 16:09:00,47.123457,-122.600000\n")
        self.assertEqual(tracks.line_errors(text), [])

    def test_a_row_with_no_time_or_no_position_is_left_out(self):
        when = datetime.datetime(2024, 9, 24, 16, 5, 27)
        text = tracks.positions_text([(None, 47.1, -122.5), (when, None, -122.5), (when, 47.1, None),
                                      (when, 47.2, -122.6)])
        self.assertEqual(text, "datetime_utc,latitude,longitude\n2024-09-24 16:05:27,47.200000,-122.600000\n")

    def test_a_time_with_a_zone_is_written_in_utc(self):
        pacific = datetime.datetime(2024, 9, 24, 9, 5, 27, tzinfo=tracks.PACIFIC)
        self.assertIn("2024-09-24 16:05:27,", tracks.positions_text([(pacific, 47.1, -122.5)]))

    def test_no_rows_is_just_the_header(self):
        self.assertEqual(tracks.positions_text([]), "datetime_utc,latitude,longitude\n")

    def test_the_gap_rule_applies_to_it_as_to_any_file(self):
        rows = [(datetime.datetime(2024, 9, 24, 16, m), 47.1 + m / 1000, -122.5) for m in (0, 5, 10, 55, 56)]
        self.assertEqual(len(tracks.to_wkt(tracks.positions_text(rows))[0].split("),(")), 2)
        lone = rows[:3] + [(datetime.datetime(2024, 9, 24, 17, 30), 47.3, -122.5)]
        self.assertEqual(len(tracks.to_wkt(tracks.positions_text(lone))[0].split("),(")), 1)
