"""The checks of each GPS file (survey/track_checks.py): what counts as a problem,
the figures, and the JSON file written for each track file."""

import json
import os
import tempfile

from django.test import SimpleTestCase, override_settings

from survey import track_checks

HEADER = "datetime_utc,latitude,longitude\n"


def text(*rows):
    return HEADER + "".join(f"{t},{lat},{lon}\n" for t, lat, lon in rows)


# About 10 knots due north: 0.0028 degrees of latitude (311 m) a minute.
STEADY = [(f"2024-07-15 10:{m:02d}:00", round(47 + 0.0028 * m, 4), -122.5) for m in range(10)]


class AnalyseTests(SimpleTestCase):

    def test_a_steady_track_has_no_problems_and_sensible_figures(self):
        found = track_checks.analyse(text(*STEADY))
        self.assertEqual(found["problems"], [])
        self.assertEqual(found["points"], 10)
        self.assertEqual((found["first"], found["last"]), ("2024-07-15 10:00:00", "2024-07-15 10:09:00"))
        self.assertEqual(found["minutes"], 9)
        self.assertAlmostEqual(found["average_knots"], 10.1, delta=0.3)
        self.assertAlmostEqual(found["top_knots"], 10.1, delta=0.3)
        self.assertAlmostEqual(found["distance_nm"], 1.51, delta=0.03)
        self.assertEqual(found["gaps"], 0)

    def test_a_row_earlier_than_the_one_before_is_listed_with_the_row_before_it(self):
        rows = STEADY[:5] + [STEADY[2]] + STEADY[5:]
        found = track_checks.analyse(text(*rows))
        [problem] = found["problems"]
        self.assertEqual(problem["code"], "backwards")
        self.assertEqual(problem["ranges"], [[6, 7]])     # line 1 is the header
        self.assertEqual(problem["label"], "Misordered Time")
        self.assertEqual(found["backwards"]["worst_seconds"], 120)
        self.assertEqual(problem["detail"], "1 row earlier than the row before, by up to 2 min")

    def test_a_jump_far_and_fast_is_an_unlikely_speed_between_its_two_rows(self):
        rows = list(STEADY)
        rows[5] = (rows[5][0], 47.2, -122.5)              # 5 km off in a minute, and back
        found = track_checks.analyse(text(*rows))
        [problem] = found["problems"]
        self.assertEqual((problem["code"], problem["label"]), ("speed", "Unlikely Speed"))
        self.assertEqual(problem["ranges"], [[6, 7], [7, 8]])
        self.assertGreater(found["speed"]["fastest_knots"], 100)

    def test_jitter_in_a_second_is_not_speed(self):
        # 60 m in one second is over 100 knots, but too short a jump to count.
        rows = [("2024-07-15 10:00:00", 47.0, -122.5), ("2024-07-15 10:00:01", 47.00054, -122.5),
                ("2024-07-15 10:00:02", 47.0, -122.5)]
        self.assertEqual(track_checks.analyse(text(*rows))["problems"], [])

    def test_two_rows_with_one_time_far_apart_are_an_unlikely_speed(self):
        rows = STEADY[:3] + [(STEADY[2][0], 47.1, -122.5)] + STEADY[3:]
        found = track_checks.analyse(text(*rows))
        self.assertEqual([p["code"] for p in found["problems"]], ["speed"])
        self.assertEqual(found["same_time_rows"], 1)

    def test_a_gap_is_counted_and_left_out_of_the_speeds(self):
        rows = STEADY + [("2024-07-15 12:00:00", 47.5, -122.5)]   # far, but after 111 quiet minutes
        found = track_checks.analyse(text(*rows))
        self.assertEqual(found["problems"], [])
        self.assertEqual((found["gaps"], found["longest_gap_minutes"]), (1, 111))

    def test_an_empty_file_is_checked_and_has_nothing(self):
        found = track_checks.analyse(HEADER)
        self.assertEqual((found["points"], found["problems"], found["first"]), (0, [], None))


class SummaryFileTests(SimpleTestCase):

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = folder.name
        patcher = override_settings(TRACK_CHECKS_DIR=self.folder)
        patcher.enable()
        self.addCleanup(patcher.disable)

    def test_a_file_written_gets_a_summary_and_a_problem_is_listed(self):
        rows = STEADY[:5] + [STEADY[2]] + STEADY[5:]
        track_checks.after_write("20240715-ABC.csv", text(*rows).encode())
        with open(os.path.join(self.folder, "20240715-ABC.csv.json")) as f:
            summary = json.load(f)
        self.assertEqual(summary["file"], "20240715-ABC.csv")
        self.assertEqual(track_checks.problems(), {"20240715-ABC.csv": ["backwards"]})

        # Saved again without the problem: no longer listed.
        track_checks.after_write("20240715-ABC.csv", text(*STEADY).encode())
        self.assertEqual(track_checks.problems(), {})
        self.assertEqual(track_checks.read("20240715-ABC.csv")["problems"], [])

    def test_a_removed_file_loses_its_summary(self):
        track_checks.after_write("20240715-ABC.csv", text(*STEADY).encode())
        track_checks.after_remove("20240715-ABC.csv")
        self.assertIsNone(track_checks.read("20240715-ABC.csv"))

    def test_earlier_versions_and_deleted_copies_are_not_checked(self):
        track_checks.after_write("_versions/20240715-ABC.csv/20250101T000000Z.csv", text(*STEADY).encode())
        track_checks.after_write("_deleted/20240715-ABC.csv/20250101T000000Z.csv", text(*STEADY).encode())
        self.assertEqual(os.listdir(self.folder), [])

    def test_a_name_reaching_outside_the_folder_is_refused(self):
        with self.assertRaises(ValueError):
            track_checks.refresh("..\\outside.csv", text(*STEADY).encode())
