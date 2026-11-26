"""How the Audit Log pages name a change: plain Title Case names, and an
Effort's number in place of its internal id."""

from django.test import SimpleTestCase

from datahealth import audit_labels as labels


class LabelTests(SimpleTestCase):

    def test_names_are_plain_title_case(self):
        for raw, shown in (("track_status", "Track Status"), ("daily_effort_id", "Effort"), ("EffortID", "Effort"),
                           ("StartTime", "Start Time"), ("TrackID", "Track ID"), ("vessel_id", "Vessel ID"),
                           ("point_count", "Point Count"), ("Research Group", "Research Group"),
                           ("End Dec Long", "End Dec Long"), ("depth_m", "Depth (m)"), ("length_nm", "Length (nm)"),
                           ("file_name", "File Name"), ("TrackFileName", "Track File Name"),
                           ("geom", "Track Line"), ("version", "Earlier Version Kept")):
            self.assertEqual(labels.field_label(raw), shown, raw)

    def test_a_shown_name_has_no_underscore_and_starts_with_a_capital(self):
        for raw in ("track_status", "daily_effort_id", "total_distance_nm", "Comments", "SurveyDate"):
            shown = labels.field_label(raw)
            self.assertNotIn("_", shown)
            self.assertTrue(shown[0].isupper(), shown)


class EffortNumberTests(SimpleTestCase):

    HASH = 5171839947084969536

    class Cursor:
        def __init__(self, rows):
            self.rows, self.asked = rows, None

        def execute(self, sql, params):
            self.asked = params

        def fetchall(self):
            return self.rows

    def test_the_ids_asked_for_are_the_ones_the_entries_name(self):
        entries = [{"daily_effort_id": {"old": None, "new": self.HASH}, "track_status": {"old": "a", "new": "b"}},
                   {"daily_effort_id": {"old": 7, "new": self.HASH}}, None]
        self.assertEqual(labels.effort_ids(entries), {7, self.HASH})

    def test_the_ids_are_looked_up_in_one_query(self):
        cursor = self.Cursor([(self.HASH, 21181)])
        self.assertEqual(labels.effort_numbers(cursor, {self.HASH}), {self.HASH: 21181})
        self.assertEqual(cursor.asked, [[self.HASH]])
        self.assertEqual(labels.effort_numbers(self.Cursor([]), set()), {})

    def test_an_effort_shows_as_its_number_not_the_internal_id(self):
        shown = labels.shown_changes({"daily_effort_id": {"old": None, "new": self.HASH},
                                      "track_status": {"old": "unassociated", "new": "available"}},
                                     {self.HASH: 21181})
        self.assertEqual(shown, [("Effort", None, 21181, "daily_effort_id"),
                                 ("Track Status", "unassociated", "available", "track_status")])
        self.assertNotIn(str(self.HASH), str(shown))

    def test_an_effort_that_has_gone_says_so(self):
        shown = labels.shown_changes({"daily_effort_id": {"old": self.HASH, "new": None}}, {})
        self.assertEqual(shown, [("Effort", "Effort Removed", None, "daily_effort_id")])

    def test_the_internal_id_is_left_out_when_the_entry_already_names_the_number(self):
        shown = labels.shown_changes({"EffortID": {"old": None, "new": 21181},
                                      "daily_effort_id": {"old": None, "new": self.HASH}}, {self.HASH: 21181})
        self.assertEqual(shown, [("Effort", None, 21181, "EffortID")])

    def test_nothing_changes_in_the_log_itself(self):
        changes = {"daily_effort_id": {"old": None, "new": self.HASH}}
        labels.shown_changes(changes, {self.HASH: 1})
        self.assertEqual(changes, {"daily_effort_id": {"old": None, "new": self.HASH}})
